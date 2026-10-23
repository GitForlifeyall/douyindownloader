#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/block_aligner.py
================================
Block-Based Audio-Video Alignment & Dynamic Scene Retiming Engine.

Core Principles:
1. Video scenes (blocks) from transcription/SRT are aligned 1:1 with dubbed speech blocks.
2. For each block, video segment is retimed (setpts) so visual scene duration EXACTLY matches speech duration.
3. Foley SFX (sfx.wav) is sliced and time-warped (atempo) alongside video so natural sound effects stay in sync.
4. Dead silence gaps between blocks are eliminated or compressed to tight natural pauses (<= 120ms).
5. Subtitles use original high-retention Montserrat ExtraBold ASS styling with dynamic OCR MarginV.
"""

import io
import os
import sys
import re
import json
import time
import shutil
import hashlib
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any, Union
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import soundfile as sf

# Ensure repo root is on sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from .env_loader import configure_runtime_environment
    configure_runtime_environment()
    from .key_pool import (
        get_active_gemini_keys,
        mark_gemini_key_dead,
        is_gemini_dead_error,
        get_active_sarvam_keys,
        mark_sarvam_key_dead,
        is_sarvam_dead_error,
        get_active_elevenlabs_keys,
        mark_elevenlabs_key_dead,
        is_elevenlabs_dead_error,
        mask_key,
    )
    from .tts_engine import load_srt_blocks, srt_to_ass
    from .tts_google import GoogleGeminiTTS, trim_audio_silence, adjust_audio_speed
    from .tts_elevenlabs import ElevenLabsTTS
except ImportError:
    from dubbing_studio.env_loader import configure_runtime_environment
    configure_runtime_environment()
    from dubbing_studio.key_pool import (
        get_active_gemini_keys,
        mark_gemini_key_dead,
        is_gemini_dead_error,
        get_active_sarvam_keys,
        mark_sarvam_key_dead,
        is_sarvam_dead_error,
        get_active_elevenlabs_keys,
        mark_elevenlabs_key_dead,
        is_elevenlabs_dead_error,
        mask_key,
    )
    from dubbing_studio.tts_engine import load_srt_blocks, srt_to_ass
    from dubbing_studio.tts_google import GoogleGeminiTTS, trim_audio_silence, adjust_audio_speed
    from dubbing_studio.tts_elevenlabs import ElevenLabsTTS



def get_media_duration(file_path: Union[str, Path]) -> float:
    """Get accurate media duration via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(file_path)
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(json.loads(r.stdout)["format"]["duration"])


def load_detected_margin_v(clean_video_path: Path) -> int:
    """Extracts dynamic MarginV from _clean_box.json or falls back to default 280."""
    candidates = [
        clean_video_path.with_name(f"{clean_video_path.stem}_box.json"),
        clean_video_path.with_name(f"{clean_video_path.stem.replace('_clean', '')}_clean_box.json"),
        clean_video_path.parent / f"{clean_video_path.stem.replace('_clean', '')}_clean_box.json",
    ]
    for c in candidates:
        if c.exists():
            try:
                data = json.loads(c.read_text(encoding="utf-8"))
                if "margin_v" in data:
                    print(f"[Block Aligner] Loaded dynamic MarginV={data['margin_v']} from {c.name}")
                    return int(data["margin_v"])
            except Exception as e:
                print(f"[Block Aligner] Warning loading {c.name}: {e}")
    return 280


def resolve_dynamic_bgm_volume(bgm_path: Optional[Union[str, Path]], default_vol: float = 0.07) -> float:
    """
    Selects 5%-7% (0.05-0.07) for dense continuous drums/synth/strings,
    or 8%-12% (0.08-0.12) for sparse pizzicato/marimba/plucked tracks.
    """
    if not bgm_path:
        return default_vol
    name = Path(bgm_path).stem.lower()
    sparse_keywords = ["tiptoe", "pizzicato", "marimba", "acoustic", "curious", "pluck", "sparse", "minimal", "xylophone", "chime"]
    if any(k in name for k in sparse_keywords):
        return 0.10
    dense_keywords = ["drum", "beat", "synth", "pad", "rock", "dense", "electronic", "strings", "orchestra", "loud", "heavy"]
    if any(k in name for k in dense_keywords):
        return 0.06
    return default_vol


def synthesize_all_blocks(
    blocks: List[Dict[str, Any]],
    cache_dir: Path,
    voice: str = "Puck",
    engine: str = "google",
    sample_rate: int = 24000
) -> List[Dict[str, Any]]:
    """
    Synthesizes speech audio for each SRT block in parallel and returns trimmed audio clips.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n[Block Aligner] Synthesizing speech for {len(blocks)} blocks via {engine} ({voice})...")

    results: List[Optional[Dict[str, Any]]] = [None] * len(blocks)

    if engine.lower() in ("sarvam", "sarvamai"):
        try:
            from .tts import generate_sarvam_tts
            from .key_pool import get_active_sarvam_keys
        except ImportError:
            from dubbing_studio.tts import generate_sarvam_tts
            from dubbing_studio.key_pool import get_active_sarvam_keys
        keys = get_active_sarvam_keys()
        sr = 48000

        def _synth_sarvam_block(i: int, b: Dict[str, Any]):
            idx = b.get("index", i)
            text = b.get("text", "").strip()
            text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
            c_file = cache_dir / f"block_sarvam_{idx:03d}_{text_hash}.wav"
            if c_file.exists() and c_file.stat().st_size > 1000:
                raw_audio, audio_sr = sf.read(str(c_file))
                if raw_audio.ndim > 1:
                    raw_audio = raw_audio.mean(axis=1)
                trimmed = trim_audio_silence(raw_audio, threshold=0.010, pad_samples=int(0.01 * audio_sr))
                dur = len(trimmed) / audio_sr
                return i - 1, {"block": b, "audio": trimmed, "sr": audio_sr, "duration": dur}

            text = b.get("text", "").strip()
            for attempt in range(6):
                try:
                    k = keys[attempt % len(keys)] if keys else None
                    generate_sarvam_tts(
                        text=text,
                        output_path=str(c_file),
                        speaker=voice or "shubh",
                        speech_sample_rate=sr,
                        api_key=k
                    )
                    raw_audio, audio_sr = sf.read(str(c_file))
                    if raw_audio.ndim > 1:
                        raw_audio = raw_audio.mean(axis=1)
                    trimmed = trim_audio_silence(raw_audio, threshold=0.010, pad_samples=int(0.01 * audio_sr))
                    dur = len(trimmed) / audio_sr
                    return i - 1, {"block": b, "audio": trimmed, "sr": audio_sr, "duration": dur}
                except Exception as e:
                    time.sleep(1.0)
            raise RuntimeError(f"Failed to synthesize Sarvam block #{idx:02d}")

        max_workers = min(6, max(1, len(keys) * 2 if keys else 2))
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(_synth_sarvam_block, i, b) for i, b in enumerate(blocks, 1)]
            for fut in as_completed(futures):
                pos, item = fut.result()
                results[pos] = item
                b = item["block"]
                print(f"  ✓ Block #{b.get('index', pos+1):02d} ready: {item['duration']:.2f}s Sarvam speech (Orig scene: {b['end']-b['start']:.2f}s)")

    elif engine.lower() in ("google", "gemini"):
        active_gemini = get_active_gemini_keys()
        if not active_gemini:
            print("\n[Block Aligner] Gemini keys exhausted before synthesis! Auto-switching full video to ElevenLabs (eleven_v4)...")
            return synthesize_all_blocks(blocks, cache_dir, voice=voice, engine="elevenlabs", sample_rate=sample_rate)

        active_speaker = voice if (voice and voice.lower() not in ("shubh", "arvind", "amartya", "puck")) else "Ludo"
        tts = GoogleGeminiTTS(default_speaker=active_speaker, model="gemini-3.8-flash-tts", style="narration")

        def _synth_google_block(i: int, b: Dict[str, Any]):
            idx = b.get("index", i)
            text = b.get("text", "").strip()
            text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
            c_file = cache_dir / f"block_google_{active_speaker.lower()}_{idx:03d}_{text_hash}.wav"
            if c_file.exists() and c_file.stat().st_size > 1000:
                raw_audio, sr = sf.read(str(c_file))
                trimmed = trim_audio_silence(raw_audio, threshold=0.010, pad_samples=int(0.01 * sr))
                dur = len(trimmed) / sr
                return i - 1, {"block": b, "audio": trimmed, "sr": sr, "duration": dur, "engine": "google"}

            text = b.get("text", "").strip()
            for attempt in range(8):
                try:
                    raw_audio, sr = tts.synthesize_single_block(text, voice=active_speaker, cache_path=c_file)
                    trimmed = trim_audio_silence(raw_audio, threshold=0.010, pad_samples=int(0.01 * sr))
                    dur = len(trimmed) / sr
                    return i - 1, {"block": b, "audio": trimmed, "sr": sr, "duration": dur, "engine": "google"}
                except Exception as e:
                    time.sleep(2.0)

            raise RuntimeError(f"Failed to synthesize block #{idx:02d} after multiple retries.")

        max_workers = 2
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [ex.submit(_synth_google_block, i, b) for i, b in enumerate(blocks, 1)]
                for fut in as_completed(futures):
                    pos, item = fut.result()
                    results[pos] = item
                    b = item["block"]
        except Exception as e:
            active_gemini = get_active_gemini_keys()
            err_msg = str(e).lower()
            if not active_gemini or "exhausted" in err_msg or "quota" in err_msg:
                print(f"\n[Block Aligner] Google Gemini keys exhausted during synthesis: {e}")
                print("  => Enforcing Single-Engine Rule: Discarding partial Google audio.")
                print("  => Re-synthesizing 100% of video with ElevenLabs (eleven_v4)...")
                for gf in cache_dir.glob("block_google_*.wav"):
                    try:
                        gf.unlink()
                    except Exception:
                        pass
                return synthesize_all_blocks(blocks, cache_dir, voice=voice, engine="elevenlabs", sample_rate=sample_rate)
            raise

    elif engine.lower() in ("elevenlabs", "eleven_labs", "11labs"):
        active_speaker = voice if (voice and voice.lower() not in ("shubh", "arvind", "amartya", "puck", "ludo", "enzo")) else "roger"
        tts = ElevenLabsTTS(default_voice=active_speaker, model="eleven_v4")

        active_keys = get_active_elevenlabs_keys()
        max_workers = min(6, max(2, len(active_keys)))

        def _synth_elevenlabs_block(i: int, b: Dict[str, Any]):
            idx = b.get("index", i)
            text = b.get("text", "").strip()
            text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
            c_file = cache_dir / f"block_elevenlabs_{active_speaker.lower()}_{idx:03d}_{text_hash}.mp3"
            if c_file.exists() and c_file.stat().st_size > 1000:
                raw_audio, sr = sf.read(str(c_file))
                if raw_audio.ndim > 1:
                    raw_audio = raw_audio.mean(axis=1)
                trimmed = trim_audio_silence(raw_audio, threshold=0.010, pad_samples=int(0.01 * sr))
                dur = len(trimmed) / sr
                return i - 1, {"block": b, "audio": trimmed, "sr": sr, "duration": dur, "engine": "elevenlabs"}

            text = b.get("text", "").strip()
            for attempt in range(8):
                try:
                    raw_audio, sr = tts.synthesize_single_block(text, voice=active_speaker, cache_path=c_file)
                    trimmed = trim_audio_silence(raw_audio, threshold=0.010, pad_samples=int(0.01 * sr))
                    dur = len(trimmed) / sr
                    return i - 1, {"block": b, "audio": trimmed, "sr": sr, "duration": dur, "engine": "elevenlabs"}
                except Exception as e:
                    time.sleep(1.0)
            raise RuntimeError(f"ElevenLabs failed to synthesize block #{idx:02d}")

        try:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [ex.submit(_synth_elevenlabs_block, i, b) for i, b in enumerate(blocks, 1)]
                for fut in as_completed(futures):
                    pos, item = fut.result()
                    results[pos] = item
                    b = item["block"]
                    print(f"  ✓ Block #{b.get('index', pos+1):02d} ready: {item['duration']:.2f}s ElevenLabs v4 speech (Orig scene: {b['end']-b['start']:.2f}s)")
        except Exception as e:
            active_el = get_active_elevenlabs_keys()
            err_msg = str(e).lower()
            if not active_el or "exhausted" in err_msg or "quota" in err_msg or "credit" in err_msg or "429" in err_msg or "failed to synthesize" in err_msg:
                print(f"\n[Block Aligner] ElevenLabs keys exhausted or failed during synthesis: {e}")
                print("  => Enforcing Single-Engine Rule: Discarding partial ElevenLabs audio.")
                print("  => Re-synthesizing 100% of video with Google Gemini Flash 3.8 TTS fallback...")
                for ef in cache_dir.glob("block_elevenlabs_*.mp3"):
                    try:
                        ef.unlink()
                    except Exception:
                        pass
                google_voice = "Ludo" if (not voice or voice.lower() in ("viraj", "brian", "adam", "shubh")) else voice
                return synthesize_all_blocks(blocks, cache_dir, voice=google_voice, engine="google", sample_rate=sample_rate)
            raise

    elif engine.lower() in ("chirp", "google_chirp", "gcloud_chirp"):
        import requests
        import base64
        chirp_key = os.getenv("GOOGLE_TTS_API_KEY") or os.getenv("GEMINI_API_KEY")
        voice_str = voice or "Orus"
        voice_lower = voice_str.lower()
        if "chirp" in voice_lower:
            chirp_voice = voice_str
        elif voice_lower in ("orus", "fenrir", "puck", "aoede", "charon", "kore", "leto"):
            chirp_voice = f"hi-IN-Chirp3-HD-{voice_str.capitalize()}"
        else:
            chirp_voice = "hi-IN-Chirp3-HD-Orus"

        def _synth_chirp_block(i: int, b: Dict[str, Any]):
            idx = b.get("index", i)
            text = b.get("text", "").strip()
            text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
            c_file = cache_dir / f"block_chirp_{chirp_voice.split('-')[-1].lower()}_{idx:03d}_{text_hash}.wav"
            if c_file.exists() and c_file.stat().st_size > 1000:
                raw_audio, sr = sf.read(str(c_file))
                trimmed = trim_audio_silence(raw_audio, threshold=0.010, pad_samples=int(0.01 * sr))
                dur = len(trimmed) / sr
                return i - 1, {"block": b, "audio": trimmed, "sr": sr, "duration": dur}

            url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={chirp_key}"
            payload = {
                "input": {"text": text},
                "voice": {"languageCode": "hi-IN", "name": chirp_voice},
                "audioConfig": {"audioEncoding": "MP3", "speakingRate": 1.05}
            }
            for attempt in range(5):
                try:
                    resp = requests.post(url, json=payload, timeout=20)
                    if resp.status_code == 200:
                        audio_bytes = base64.b64decode(resp.json()["audioContent"])
                        raw_audio, sr = sf.read(io.BytesIO(audio_bytes))
                        if raw_audio.ndim > 1:
                            raw_audio = raw_audio.mean(axis=1)
                        sf.write(str(c_file), raw_audio, sr)
                        trimmed = trim_audio_silence(raw_audio, threshold=0.010, pad_samples=int(0.01 * sr))
                        dur = len(trimmed) / sr
                        return i - 1, {"block": b, "audio": trimmed, "sr": sr, "duration": dur}
                    time.sleep(1.0)
                except Exception:
                    time.sleep(1.0)
            raise RuntimeError(f"Chirp synthesis failed for block #{idx:02d}")

        max_workers = 3
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(_synth_chirp_block, i, b) for i, b in enumerate(blocks, 1)]
            for fut in as_completed(futures):
                pos, item = fut.result()
                results[pos] = item
                b = item["block"]
                print(f"  ✓ Block #{b.get('index', pos+1):02d} ready: {item['duration']:.2f}s Chirp speech (Orig scene: {b['end']-b['start']:.2f}s)")

    return [r for r in results if r is not None]


def align_video_and_audio_blocks(
    clean_video_path: Path,
    srt_path: Path,
    output_video_path: Path,
    sfx_path: Optional[Path] = None,
    bgm_path: Optional[Path] = None,
    voice: str = "shubh",
    engine: str = "sarvam",
    work_dir: Optional[Path] = None,
    max_silence_sec: float = 0.20
) -> Path:
    """
    Executes Block-Based Dubbing with UNIFORM Audio Scaling & Max 200ms Silences:
    1. Synthesizes all blocks at natural 1.0x human cadence via Sarvam AI.
    2. Sequences audio blocks with inter-block silences clamped to max 200ms.
    3. Scales the final voiceover at ONE uniform tempo rate (NO individual block tempo fluctuations).
    4. Harmonizes video B-roll with uniform pacing (no jittery per-scene video retiming).
    5. Layers 3 audio stems (Voiceover + Isolated SFX + Royalty-free BGM) and ASS captions.
    """
    clean_video_path = Path(clean_video_path)
    srt_path = Path(srt_path)
    output_video_path = Path(output_video_path)
    output_video_path.parent.mkdir(parents=True, exist_ok=True)

    if not work_dir:
        work_dir = output_video_path.parent / f"align_work_{clean_video_path.stem}"
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    temp_audio_dir = work_dir / "temp_audio_blocks"
    temp_audio_dir.mkdir(parents=True, exist_ok=True)

    blocks = load_srt_blocks(srt_path)
    if not blocks:
        raise ValueError(f"No subtitle blocks found in {srt_path}")

    vid_dur = get_media_duration(clean_video_path)

    # 1. Synthesize Audio for each block at natural 1.0x pace
    block_items = synthesize_all_blocks(
        blocks=blocks,
        cache_dir=temp_audio_dir,
        voice=voice,
        engine=engine
    )

    actual_engine = block_items[0].get("engine", engine) if block_items else engine
    if actual_engine != engine:
        print(f"\n[Block Aligner] Engine reconciled to: {actual_engine.upper()}")
        engine = actual_engine
        if actual_engine == "elevenlabs" and "_google" in output_video_path.name:
            output_video_path = output_video_path.with_name(output_video_path.name.replace("_google", "_elevenlabs"))
            print(f"[Block Aligner] Updated output video target filename: {output_video_path.name}")
        elif actual_engine == "google" and "_elevenlabs" in output_video_path.name:
            output_video_path = output_video_path.with_name(output_video_path.name.replace("_elevenlabs", "_google"))
            print(f"[Block Aligner] Updated output video target filename: {output_video_path.name}")

    # 2. Plan Unscaled Timeline: Silences capped at max 200ms, ZERO individual block warping

    # 2. Plan Unscaled Timeline with Proportional Drift Redistribution (Option 3)
    # If blocks run slightly long, gently compress earlier inter-block pauses so the final lines never get squeezed!
    total_speech_len = sum(it["duration"] for it in block_items)
    num_transitions = max(1, len(block_items) - 1)
    available_pause_budget = max(0.0, vid_dur - total_speech_len)
    
    # Calculate target pause per transition: ideally 0.05s - 0.20s, but compressed if speech is long
    ideal_pause = min(max_silence_sec, max(0.015, available_pause_budget / num_transitions))
    print(f"\n[Block Aligner] Dynamic Drift Redistribution: Speech: {total_speech_len:.2f}s | Target pause per cut: {ideal_pause*1000:.0f}ms")

    aligned_plan = []
    current_timeline_time = 0.02  # Instant start on frame 1

    print(f"\n[Block Aligner] Sequencing blocks on timeline (Adaptive Pause: {ideal_pause*1000:.0f}ms, Max: {max_silence_sec*1000:.0f}ms)...")
    for idx, item in enumerate(block_items, 1):
        b = item["block"]
        orig_start = b["start"]
        orig_end = b["end"]
        orig_dur = max(0.1, orig_end - orig_start)
        speech_dur = max(0.1, item["duration"])
        is_last = (idx == len(block_items))
        if is_last:
            # Strictly zero trailing silence on the final line for seamless loop!
            mask = np.abs(item["audio"]) > 0.010
            if np.any(mask):
                last_idx = np.where(mask)[0][-1]
                item["audio"] = item["audio"][:last_idx + 1]
                speech_dur = len(item["audio"]) / item["sr"]

        # Determine inter-block silence using dynamic drift redistribution
        if idx > 1:
            prev_b = block_items[idx - 2]["block"]
            orig_gap = orig_start - prev_b["end"]
            if orig_gap > 0:
                silence_gap = min(orig_gap, ideal_pause)
            else:
                silence_gap = min(0.05, ideal_pause)

            # Ensure a natural micro-breath gap (>=60ms) before penultimate and final lines
            if idx >= len(block_items) - 1:
                silence_gap = max(0.06, silence_gap)

            start_new = current_timeline_time + silence_gap
        else:
            silence_gap = 0.02
            start_new = current_timeline_time

        end_new = start_new + speech_dur
        current_timeline_time = end_new

        aligned_plan.append({
            "index": idx,
            "orig_start": orig_start,
            "orig_end": orig_end,
            "orig_dur": orig_dur,
            "speech_dur": speech_dur,
            "raw_start": start_new,
            "raw_end": end_new,
            "text": b.get("text", ""),
            "audio": item["audio"],
            "sr": item["sr"]
        })

        gap_str = f" [Pause: {silence_gap*1000:.0f}ms]" if idx > 1 else ""
        print(f"  Block #{idx:02d}: {speech_dur:.2f}s speech placed at [{start_new:.2f}s -> {end_new:.2f}s]{gap_str}")

    raw_total_speech_dur = current_timeline_time
    print(f"\n[Block Aligner] Total Unscaled Speech Duration: {raw_total_speech_dur:.2f}s (Original Video: {vid_dur:.2f}s)")

    # 3. Assemble Raw Master Audio Buffer (100% natural, unwarped)
    sr_master = block_items[0]["sr"]
    total_samples = int((raw_total_speech_dur + 2.0) * sr_master)
    voice_raw_buffer = np.zeros(total_samples, dtype=np.float32)

    for p in aligned_plan:
        start_samp = int(p["raw_start"] * sr_master)
        audio = p["audio"]
        if p["sr"] != sr_master:
            audio = np.interp(
                np.linspace(0, len(audio), int(len(audio) * (sr_master / p["sr"]))),
                np.arange(len(audio)),
                audio
            )
        end_samp = start_samp + len(audio)
        if end_samp > len(voice_raw_buffer):
            voice_raw_buffer = np.pad(voice_raw_buffer, (0, end_samp - len(voice_raw_buffer) + sr_master * 5))
        voice_raw_buffer[start_samp:end_samp] += audio

    raw_voice_wav = work_dir / "raw_unscaled_voice.wav"
    sf.write(str(raw_voice_wav), voice_raw_buffer[:int(raw_total_speech_dur * sr_master)], sr_master)

    # 4. Apply ONE UNIFORM Tempo Scaling across the ENTIRE voiceover track
    ideal_audio_tempo = raw_total_speech_dur / vid_dur
    # Allow uniform tempo scaling up to 1.25x for energetic viral pacing without voice distortion.
    # If speech is shorter than video, allow gentle expansion down to 0.95x.
    uniform_audio_tempo = max(0.95, min(1.25, ideal_audio_tempo))
    timed_voice_wav = work_dir / "timed_uniform_voice.wav"

    print(f"\n[Block Aligner] UNIFORM Voice Pacing: Entire narration scaled at {uniform_audio_tempo:.4f}x (Allowed 0.95x-1.25x)")
    cmd_tempo = [
        "ffmpeg", "-y",
        "-i", str(raw_voice_wav),
        "-filter:a", f"atempo={uniform_audio_tempo:.5f}",
        str(timed_voice_wav)
    ]
    subprocess.run(cmd_tempo, capture_output=True, check=True)
    timed_voice_dur = get_media_duration(timed_voice_wav)
    print(f"[Block Aligner] Final Timed Voiceover Duration: {timed_voice_dur:.2f}s (Original Video: {vid_dur:.2f}s)")

    # 5. Determine Video Duration & Uniform Pacing Adjustment
    # CRITICAL LOOP RULE: Voiceover audio must NEVER be cut off at the tail!
    # The final sentence is the crucial loop-closing bridge. Video duration is synchronized
    # to match the timed voiceover duration exactly so the audio is 100% complete.
    target_video_dur = timed_voice_dur
    video_speedup = vid_dur / timed_voice_dur
    if abs(video_speedup - 1.0) > 0.01:
        print(f"[Block Aligner] Video B-roll pacing adjusted by {video_speedup:.4f}x ({vid_dur:.2f}s -> {target_video_dur:.2f}s) to guarantee zero audio cutoff.")

    aligned_voice_wav = timed_voice_wav
    # Handle Foley SFX Track (scaled uniformly with video)
    final_audio_path = aligned_voice_wav
    aligned_sfx_wav = None
    if sfx_path and Path(sfx_path).exists():
        print(f"[Block Aligner] Layering synchronized SFX from {Path(sfx_path).name} (Uniform tempo: {video_speedup:.4f}x)...")
        aligned_sfx_wav = work_dir / "aligned_sfx.wav"
        if abs(video_speedup - 1.0) > 0.01:
            cmd_sfx = [
                "ffmpeg", "-y",
                "-i", str(sfx_path),
                "-filter:a", f"atempo={video_speedup:.5f}",
                str(aligned_sfx_wav)
            ]
        else:
            cmd_sfx = [
                "ffmpeg", "-y",
                "-i", str(sfx_path),
                "-c:a", "copy",
                str(aligned_sfx_wav)
            ]
        subprocess.run(cmd_sfx, capture_output=True, check=True)

    # Resolve Royalty-Free Background Music from assets/background_audio/
    resolved_bgm = None
    if bgm_path and Path(bgm_path).exists() and Path(bgm_path).is_file():
        resolved_bgm = Path(bgm_path)
    else:
        bgm_candidates_dirs = [
            root_dir / "assets/background_audio",
            Path("assets/background_audio"),
            Path(__file__).resolve().parent.parent / "assets/background_audio",
        ]
        for d in bgm_candidates_dirs:
            if d and d.exists() and d.is_dir():
                tracks = sorted([f for f in d.glob("*.mp3")] + [f for f in d.glob("*.wav")])
                if tracks:
                    resolved_bgm = tracks[0]
                    break


    # Broadcast De-robotic Voice Mastering Chain:
    # 1. 85Hz Highpass (eliminates mic rumble/boom)
    # 2. 180Hz Warmth (+1.8dB broad bell for rich human chest resonance)
    # 3. 420Hz Boxiness Cut (-3.8dB bell removes synthetic/nasal cardboard buildup)
    # 4. 3.1kHz Harshness Notch (-2.2dB bell tames aggressive synthetic rasp)
    # 5. 7.2kHz Air/De-ess (-2.8dB bell smooths digital sibilance)
    # 6. Soft-Clipping (atan harmonic saturation for analog warmth)
    # 7. Broadcast Transparent Compression (2.8:1 ratio, smooth leveling)
    # 8. EBU R128 Loudness Normalization (-14 LUFS, true peak -1.5dB)
    voice_master_af = (
        "highpass=f=85:p=2,"
        "equalizer=f=180:width_type=q:w=1.2:g=1.8,"
        "equalizer=f=420:width_type=q:w=1.8:g=-3.8,"
        "equalizer=f=3100:width_type=q:w=2.0:g=-2.2,"
        "equalizer=f=7200:width_type=q:w=1.6:g=-2.8,"
        "asoftclip=type=atan:threshold=0.88,"
        "acompressor=threshold=-18dB:ratio=2.8:attack=12:release=140:makeup=1.5,"
        "loudnorm=I=-14:TP=-1.5:LRA=7"
    )

    # 3-Stem Dynamic Audio Mastering: mastered voice + agate noise gate + sidechain ducked SFX + dynamic BGM
    mixed_audio = work_dir / "aligned_mixed_audio.wav"
    bgm_vol = resolve_dynamic_bgm_volume(resolved_bgm) if resolved_bgm else 0.07

    if aligned_sfx_wav and aligned_sfx_wav.exists() and resolved_bgm and resolved_bgm.exists():
        print(f"[Block Aligner] Dynamic 3-Stem Mastering: Broadcast Mastered Voiceover (-14 LUFS) + SFX (agate gate + sidechain ducked 0.70) + BGM ({resolved_bgm.name}, {bgm_vol*100:.1f}%)...")
        filter_mix = (
            f"[0:a]{voice_master_af},asplit=2[voice_main][voice_key];"
            "[1:a]agate=threshold=0.008:range=0.1:attack=10:release=150,volume=0.70[sfx_clean];"
            "[sfx_clean][voice_key]sidechaincompress=threshold=0.04:ratio=4:attack=5:release=200[sfx_ducked];"
            f"[2:a]volume={bgm_vol:.2f}[music];"
            "[voice_main][sfx_ducked][music]amix=inputs=3:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.89[aout]"
        )
        cmd_mix = [
            "ffmpeg", "-y",
            "-i", str(aligned_voice_wav),
            "-i", str(aligned_sfx_wav),
            "-stream_loop", "-1", "-i", str(resolved_bgm),
            "-filter_complex", filter_mix,
            "-map", "[aout]",
            "-c:a", "pcm_s16le",
            "-t", f"{target_video_dur:.3f}",
            str(mixed_audio)
        ]
        subprocess.run(cmd_mix, capture_output=True, check=True)
        final_audio_path = mixed_audio

    elif aligned_sfx_wav and aligned_sfx_wav.exists():
        print(f"[Block Aligner] Dynamic 2-Stem Mastering: Broadcast Mastered Voiceover (-14 LUFS) + SFX (agate gate + sidechain ducked 0.70)...")
        filter_mix = (
            f"[0:a]{voice_master_af},asplit=2[voice_main][voice_key];"
            "[1:a]agate=threshold=0.008:range=0.1:attack=10:release=150,volume=0.70[sfx_clean];"
            "[sfx_clean][voice_key]sidechaincompress=threshold=0.04:ratio=4:attack=5:release=200[sfx_ducked];"
            "[voice_main][sfx_ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.89[aout]"
        )
        cmd_mix = [
            "ffmpeg", "-y",
            "-i", str(aligned_voice_wav),
            "-i", str(aligned_sfx_wav),
            "-filter_complex", filter_mix,
            "-map", "[aout]",
            "-c:a", "pcm_s16le",
            "-t", f"{target_video_dur:.3f}",
            str(mixed_audio)
        ]
        subprocess.run(cmd_mix, capture_output=True, check=True)
        final_audio_path = mixed_audio

    elif resolved_bgm and resolved_bgm.exists():
        print(f"[Block Aligner] Dynamic 2-Stem Mastering: Broadcast Mastered Voiceover (-14 LUFS) + BGM ({resolved_bgm.name}, {bgm_vol*100:.1f}%)...")
        filter_mix = (
            f"[0:a]{voice_master_af}[voice_main];"
            f"[1:a]volume={bgm_vol:.2f}[music];"
            "[voice_main][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.89[aout]"
        )
        cmd_mix = [
            "ffmpeg", "-y",
            "-i", str(aligned_voice_wav),
            "-stream_loop", "-1", "-i", str(resolved_bgm),
            "-filter_complex", filter_mix,
            "-map", "[aout]",
            "-c:a", "pcm_s16le",
            "-t", f"{target_video_dur:.3f}",
            str(mixed_audio)
        ]
        subprocess.run(cmd_mix, capture_output=True, check=True)
        final_audio_path = mixed_audio

    else:
        # Master standalone voiceover even without stems
        print("[Block Aligner] Dynamic 1-Stem Mastering: Broadcast Mastered Voiceover (-14 LUFS)...")
        cmd_master = [
            "ffmpeg", "-y",
            "-i", str(aligned_voice_wav),
            "-af", voice_master_af,
            "-c:a", "pcm_s16le",
            "-t", f"{target_video_dur:.3f}",
            str(mixed_audio)
        ]
        subprocess.run(cmd_master, capture_output=True, check=True)
        final_audio_path = mixed_audio

    # 5. Generate Frame-Accurate Aligned Subtitles (Scaled by Uniform Audio Tempo)
    print("\n[Block Aligner] Generating synchronized ASS subtitles with original styling...")
    aligned_srt_path = work_dir / f"{clean_video_path.stem}_aligned.srt"
    with open(aligned_srt_path, "w", encoding="utf-8") as f:
        for p in aligned_plan:
            def to_srt_time(sec: float) -> str:
                h = int(sec // 3600)
                m = int((sec % 3600) // 60)
                s = int(sec % 60)
                ms = int(round((sec - int(sec)) * 1000))
                return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
            scaled_start = p["raw_start"] / uniform_audio_tempo
            scaled_end = p["raw_end"] / uniform_audio_tempo
            # Strip inline audio tags [tag] so subtitles display only clean spoken dialogue
            clean_sub_text = re.sub(r"\[[a-zA-Z\s]+\]", "", p["text"]).strip()
            clean_sub_text = " ".join(clean_sub_text.split())
            f.write(f"{p['index']}\n{to_srt_time(scaled_start)} --> {to_srt_time(scaled_end)}\n{clean_sub_text}\n\n")

    dynamic_margin_v = load_detected_margin_v(clean_video_path)
    aligned_ass_path = work_dir / f"{clean_video_path.stem}_aligned.ass"

    # Save synchronized colloquial Roman Hinglish SRT using text_to_hinglish transliterator
    try:
        from dubbing_studio.hinglish import srt_to_hinglish
        aligned_hinglish_srt = work_dir / f"{clean_video_path.stem}_aligned_hinglish.srt"
        aligned_hinglish_srt.write_text(srt_to_hinglish(aligned_srt_path.read_text(encoding="utf-8")), encoding="utf-8")
        print(f"[Block Aligner] Mapped Devanagari SRT to Roman Hinglish: {aligned_hinglish_srt.name}")
        sub_for_ass = aligned_hinglish_srt
    except Exception as e:
        print(f"[Block Aligner] Notice: Transliterator fallback ({e}); using aligned SRT.")
        sub_for_ass = aligned_srt_path

    srt_to_ass(
        srt_path=sub_for_ass,
        ass_path=aligned_ass_path,
        font_name="Montserrat ExtraBold",
        font_size=120,
        margin_v=dynamic_margin_v,
        to_hinglish=True
    )

    # 6. Final Mux: Single-Pass Video Rendering with Uniform Pacing
    print(f"\n[Block Aligner] Muxing final video to: {output_video_path} (Target duration: {target_video_dur:.2f}s)...")
    escaped_ass = str(aligned_ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
    vf_parts = []
    if abs(video_speedup - 1.0) > 0.01:
        vf_parts.append(f"setpts=PTS/{video_speedup:.5f}")
    vf_parts.append(f"subtitles='{escaped_ass}'")
    video_filter = ",".join(vf_parts)

    cmd_mux = [
        "ffmpeg", "-y",
        "-i", str(clean_video_path),
        "-i", str(final_audio_path),
        "-vf", video_filter,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{target_video_dur:.3f}",
        "-shortest",
        str(output_video_path)
    ]
    mux_log = work_dir / "ffmpeg_mux.log"
    with open(mux_log, "w", encoding="utf-8", errors="replace") as f_log:
        res = subprocess.run(cmd_mux, stdout=f_log, stderr=subprocess.STDOUT)
    if res.returncode != 0:
        err_tail = mux_log.read_text(encoding="utf-8", errors="replace")[-1000:]
        print(f"[Block Aligner] Mux Error:\n{err_tail}")
        raise subprocess.CalledProcessError(res.returncode, cmd_mux, output=err_tail)

    print(f"\n🎉 [SUCCESS] Uniform Aligned Video Ready!")
    print(f"   📹 File: {output_video_path}")
    print(f"   ⏱️ Duration: {target_video_dur:.2f}s")
    print(f"   🎙️ Voice Engine: {engine.capitalize()} ({voice}) | Scaling: {uniform_audio_tempo:.4f}x (Uniform across all blocks)")

    return output_video_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Block-Based Audio-Video Alignment Dubbing Engine")
    parser.add_argument("--video", "-v", type=str, required=True, help="Path to clean video")
    parser.add_argument("--srt", "-s", type=str, required=True, help="Path to hinglish SRT blocks")
    parser.add_argument("--sfx", type=str, default=None, help="Path to isolated sfx.wav stem")
    parser.add_argument("--voice", type=str, default="shubh", help="TTS voice (shubh for Sarvam)")
    parser.add_argument("--engine", type=str, default="sarvam", help="sarvam or google")
    parser.add_argument("--output", "-o", type=str, default=None, help="Path to output video")
    args = parser.parse_args()

    v_path = Path(args.video)
    s_path = Path(args.srt)
    o_path = Path(args.output) if args.output else v_path.parent.parent / "final_videos" / f"{v_path.stem.replace('_clean', '')}_sarvam_aligned.mp4"

    align_video_and_audio_blocks(
        clean_video_path=v_path,
        srt_path=s_path,
        output_video_path=o_path,
        sfx_path=Path(args.sfx) if args.sfx else None,
        voice=args.voice,
        engine=args.engine
    )
