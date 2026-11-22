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
import difflib
import subprocess
import threading
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any, Union
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import soundfile as sf

_WORD_ALIGN_WHISPER_CACHE: Any = None
_WORD_ALIGN_WHISPER_LOCK = threading.Lock()
_FFMPEG_NVENC_AVAIL: Optional[bool] = None


def _get_word_align_whisper_model():
    """Singleton cache for faster-whisper base model used for word-synced ASS captions (CUDA preferred, CPU fallback)."""
    global _WORD_ALIGN_WHISPER_CACHE
    with _WORD_ALIGN_WHISPER_LOCK:
        if _WORD_ALIGN_WHISPER_CACHE is None:
            from faster_whisper import WhisperModel
            import torch
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            ctype = "float16" if dev == "cuda" else "int8"
            try:
                if dev == "cuda":
                    torch.cuda.empty_cache()
                _WORD_ALIGN_WHISPER_CACHE = WhisperModel("base", device=dev, compute_type=ctype)
                print(f"[Block Aligner] Loaded Word-Sync Whisper (base, {dev}, {ctype}).")
            except Exception as e:
                print(f"[Block Aligner] CUDA Whisper init error ({e}); falling back to CPU int8...")
                _WORD_ALIGN_WHISPER_CACHE = WhisperModel("base", device="cpu", compute_type="int8")
        return _WORD_ALIGN_WHISPER_CACHE


def _ffmpeg_has_nvenc() -> bool:
    """Detect whether FFmpeg supports hardware h264_nvenc encoding."""
    global _FFMPEG_NVENC_AVAIL
    if _FFMPEG_NVENC_AVAIL is not None:
        return _FFMPEG_NVENC_AVAIL
    try:
        res = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=5)
        _FFMPEG_NVENC_AVAIL = "h264_nvenc" in (res.stdout or "")
    except Exception:
        _FFMPEG_NVENC_AVAIL = False
    return _FFMPEG_NVENC_AVAIL

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
    from .tts_google import GoogleGeminiTTS, trim_audio_silence, adjust_audio_speed, extract_audio_tags_and_clean_text
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
    from dubbing_studio.tts_google import GoogleGeminiTTS, trim_audio_silence, adjust_audio_speed, extract_audio_tags_and_clean_text
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


def normalize_aspect_ratio(ratio: Optional[str]) -> str:
    """Normalize aspect ratio option into canonical 'reel' (default 9:16) or 'square' (1:1)."""
    val = str(ratio or "reel").strip().lower()
    if val in ("square", "1:1", "1/1", "sq"):
        return "square"
    return "reel"


def _generate_word_synced_movie_ass(
    aligned_voice_wav: Path,
    aligned_plan: List[Dict[str, Any]],
    ass_path: Path,
    uniform_audio_tempo: float,
    target_lang: str = "English",
    target_w: int = 1080,
    target_h: int = 1920,
    margin_v: int = 510,
    ratio: str = "reel",
) -> Path:
    """
    Generate 100% word-for-word acoustically synced ASS captions for Movie/Reels mode
    matching the heavy ultra-bold italic display style (white fill, crisp black stroke,
    solid black drop shadow, one ALL-CAPS word per beat).
    """
    def _to_ass_time(sec: float) -> str:
        sec = max(0.0, float(sec))
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        cs = min(99, int(round((sec - int(sec)) * 100)))
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    # Extract clean script words preserving exact spelling + fallback block windows
    script_words: List[str] = []
    fallback_events: List[Tuple[float, float, str]] = []

    is_devanagari = any(
        "\u0900" <= ch <= "\u097f"
        for p in aligned_plan[:10]
        for ch in str(p.get("text", ""))
    )
    to_hinglish_fn = None
    if is_devanagari:
        try:
            from .hinglish import text_to_hinglish as _tth
            to_hinglish_fn = _tth
        except Exception:
            try:
                from dubbing_studio.hinglish import text_to_hinglish as _tth
                to_hinglish_fn = _tth
            except Exception:
                to_hinglish_fn = None

    for p in aligned_plan:
        txt = re.sub(r"\[[a-zA-Z\s]+\]", "", str(p.get("text", ""))).strip()
        if to_hinglish_fn:
            txt = to_hinglish_fn(txt)
        words_in_block = [w.strip(".,;:!?\"'—–-…").upper() for w in txt.split()]
        words_in_block = [w for w in words_in_block if w]
        if not words_in_block:
            continue
        b_s = float(p["raw_start"]) / uniform_audio_tempo
        b_e = float(p["raw_end"]) / uniform_audio_tempo
        step = max(0.05, b_e - b_s) / len(words_in_block)
        for k, w in enumerate(words_in_block):
            script_words.append(w)
            fallback_events.append((b_s + k * step, b_s + (k + 1) * step, w))

    word_events: List[Tuple[float, float, str]] = []
    whisper_lang = "en" if str(target_lang or "").strip().lower().startswith("en") else None
    try:
        w_model = _get_word_align_whisper_model()
        segs, _ = w_model.transcribe(
            str(aligned_voice_wav),
            language=whisper_lang,
            beam_size=1,
            word_timestamps=True,
            vad_filter=True,
        )
        w_items = []
        for seg in segs:
            for w in (seg.words or []):
                tok = w.word.strip()
                norm = re.sub(r"[^a-z0-9]", "", tok.lower())
                if norm:
                    w_items.append((float(w.start), float(w.end), norm, tok))

        if script_words and w_items:
            s_norms = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in script_words]
            w_norms = [x[2] for x in w_items]
            sm = difflib.SequenceMatcher(None, s_norms, w_norms)
            mapped: List[Optional[Tuple[float, float, str]]] = [None] * len(script_words)
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag == "equal":
                    for k in range(i2 - i1):
                        mapped[i1 + k] = (w_items[j1 + k][0], w_items[j1 + k][1], script_words[i1 + k])
                elif tag == "replace" and (i2 - i1) > 0 and (j2 - j1) > 0:
                    fb_s = fallback_events[i1][0]
                    fb_e = fallback_events[i2 - 1][1]
                    span_s = max(fb_s - 0.5, w_items[j1][0])
                    span_e = min(fb_e + 0.5, w_items[j2 - 1][1])
                    if span_e <= span_s or (span_e - span_s) > max(1.0 * (i2 - i1), (fb_e - fb_s) + 1.0):
                        span_s, span_e = fb_s, fb_e
                    n = i2 - i1
                    step = max(0.04, span_e - span_s) / n
                    for k in range(n):
                        mapped[i1 + k] = (span_s + k * step, span_s + (k + 1) * step, script_words[i1 + k])
                elif tag == "delete" and (i2 - i1) > 0:
                    fb_s = fallback_events[i1][0]
                    fb_e = fallback_events[i2 - 1][1]
                    span_s = max(fb_s, w_items[j1 - 1][1] if j1 > 0 else fb_s)
                    span_e = min(fb_e, w_items[j1][0] if j1 < len(w_items) else fb_e)
                    n = i2 - i1
                    if span_e <= span_s or (span_e - span_s) > max(0.8 * n, (fb_e - fb_s) + 0.6):
                        span_s, span_e = fb_s, fb_e
                    step = max(0.04, span_e - span_s) / n
                    for k in range(n):
                        mapped[i1 + k] = (span_s + k * step, span_s + (k + 1) * step, script_words[i1 + k])
            word_events = [m for m in mapped if m is not None]
            print(f"[Block Aligner] 100% Word-Synced Movie Captions: mapped {len(word_events)}/{len(script_words)} script words via Whisper timestamps.")
        elif w_items:
            word_events = [(st, en, tok.strip(".,;:!?\"'—–-…").upper()) for st, en, _, tok in w_items if tok.strip(".,;:!?\"'—–-…")]
    except Exception as e:
        print(f"[Block Aligner] Notice: Whisper word sync unavailable ({e}); using aligned fallback timing.")

    if not word_events:
        word_events = fallback_events

    # Tighten consecutive transitions smoothly without overlap while preserving real pauses (>120ms)
    normalized_events: List[Tuple[float, float, str]] = []
    for idx_w, (st, en, wd) in enumerate(word_events):
        en = max(st + 0.05, en)
        if idx_w + 1 < len(word_events):
            next_st = word_events[idx_w + 1][0]
            if next_st < en:
                en = max(st + 0.04, next_st)
            elif (next_st - en) <= 0.12:
                en = next_st
        normalized_events.append((st, en, wd))

    ratio_norm = normalize_aspect_ratio(ratio)
    if ratio_norm == "square":
        # Match reference square caption style: condensed bold-italic uppercase white Impact with crisp outline & drop shadow
        sq_font_size = max(48, int(round(target_h * (84.0 / 1080.0))))
        sq_margin_v = max(48, int(round(target_h * 0.10)))
        style_line = (
            f"Style: Default,Impact,{sq_font_size},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
            f"-1,-1,0,0,96,100,1,0,1,3.8,4.5,2,40,40,{sq_margin_v},1"
        )
    else:
        style_line = (
            f"Style: Default,Montserrat ExtraBold,108,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
            f"-1,0,0,0,100,100,1,0,1,3.5,6.5,2,40,40,{margin_v},1"
        )

    ass_header = f"""[Script Info]
; Movie/Square 100% Word-Synced Heavy Display Style (White Fill + Thick Black Stroke + Solid Drop Shadow)
ScriptType: v4.00+
PlayResX: {target_w}
PlayResY: {target_h}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style_line}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [
        f"Dialogue: 0,{_to_ass_time(st)},{_to_ass_time(en)},Default,,0,0,0,,{wd}"
        for st, en, wd in normalized_events
    ]
    ass_path.write_text(ass_header + "\n".join(lines) + "\n", encoding="utf-8")
    return ass_path


def resolve_dynamic_bgm_volume(bgm_path: Optional[Union[str, Path]], default_vol: float = 0.18, bgm_volume: float = 1.0) -> float:
    """
    Selects balanced BGM gain (0.14-0.22) scaled by user bgm_volume multiplier
    so the royalty-free BGM stays clearly audible while sitting smoothly under -14 LUFS voiceover.
    """
    if not bgm_path:
        return max(0.05, min(0.45, default_vol * bgm_volume))
    name = Path(bgm_path).stem.lower()
    sparse_keywords = ["tiptoe", "pizzicato", "marimba", "acoustic", "curious", "pluck", "sparse", "minimal", "xylophone", "chime"]
    if any(k in name for k in sparse_keywords):
        base = 0.22
    else:
        dense_keywords = ["drum", "beat", "synth", "pad", "rock", "dense", "electronic", "strings", "orchestra", "loud", "heavy"]
        base = 0.15 if any(k in name for k in dense_keywords) else default_vol
    return max(0.05, min(0.45, base * float(bgm_volume)))


def _next_fallback_engine(current_engine: str, visited: Optional[set] = None) -> Optional[str]:
    """Return next TTS engine in priority waterfall: elevenlabs -> google -> sarvam -> chirp -> kokoro."""
    visited = visited or set()
    cur = str(current_engine or "").strip().lower()
    if cur in ("eleven_labs", "11labs"):
        cur = "elevenlabs"
    elif cur in ("gemini",):
        cur = "google"
    elif cur in ("sarvamai",):
        cur = "sarvam"
    elif cur in ("google_chirp", "gcloud_chirp"):
        cur = "chirp"
    elif cur in ("local", "kokoro_onnx"):
        cur = "kokoro"

    # User preference: If Google Flash finishes, fall back directly to ElevenLabs
    if cur == "google" and "elevenlabs" not in visited and get_active_elevenlabs_keys():
        return "elevenlabs"

    order = ["elevenlabs", "google", "sarvam", "chirp", "kokoro"]
    if cur not in order:
        return "elevenlabs" if get_active_elevenlabs_keys() else "google"
    idx = order.index(cur)
    for nxt in order[idx + 1:]:
        if nxt not in visited:
            return nxt
    return None


def _ensure_kokoro_tts():
    """Load or auto-install & download Kokoro ONNX model for 100% local offline synthesis."""
    import importlib
    import subprocess as _sp
    import urllib.request as _req

    try:
        importlib.import_module("kokoro_onnx")
    except ImportError:
        print("[Kokoro Fallback] Installing kokoro-onnx package for local TTS fallback...")
        _sp.check_call([sys.executable, "-m", "pip", "install", "-q", "kokoro-onnx"])

    models_dir = root_dir / "models" / "kokoro"
    models_dir.mkdir(parents=True, exist_ok=True)
    model_file = models_dir / "kokoro-v1.0.onnx"
    voices_file = models_dir / "voices-v1.0.bin"

    alt_voices = Path(r"C:\Users\rudra\PycharmProjects\captions videos maker\voices-v1.0.bin")
    if not voices_file.exists() and alt_voices.exists():
        import shutil as _shutil
        _shutil.copy2(str(alt_voices), str(voices_file))

    base_dl = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
    if not model_file.exists() or model_file.stat().st_size < 50_000_000:
        print(f"[Kokoro Fallback] Downloading kokoro-v1.0.onnx to {model_file}...")
        _req.urlretrieve(f"{base_dl}/kokoro-v1.0.onnx", str(model_file))
    if not voices_file.exists() or voices_file.stat().st_size < 1_000_000:
        print(f"[Kokoro Fallback] Downloading voices-v1.0.bin to {voices_file}...")
        _req.urlretrieve(f"{base_dl}/voices-v1.0.bin", str(voices_file))

    from .tts_engine import KokoroTTS
    return KokoroTTS(model_path=model_file, voices_path=voices_file)


def synthesize_all_blocks(
    blocks: List[Dict[str, Any]],
    cache_dir: Path,
    voice: str = "Puck",
    engine: str = "google",
    sample_rate: int = 24000,
    target_lang: str = "Hindi",
    allow_fallback: bool = True,
    exhausted_engines: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """
    Synthesizes speech audio for each SRT block in parallel and returns trimmed audio clips.
    Supports strict waterfall fallback: elevenlabs -> google -> sarvam (bulbul:v4-flash) -> chirp -> kokoro.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    visited = set(exhausted_engines or set())
    eng_norm = str(engine or "elevenlabs").strip().lower()
    print(f"\n[Block Aligner] Synthesizing speech for {len(blocks)} blocks via {engine} ({voice})...")

    results: List[Optional[Dict[str, Any]]] = [None] * len(blocks)

    def _cascade_to_next(failed_eng: str, reason: str, pattern: str):
        visited.add(failed_eng)
        nxt = _next_fallback_engine(failed_eng, visited=visited)
        while nxt and nxt in visited:
            nxt = _next_fallback_engine(nxt, visited=visited)
        if not allow_fallback or not nxt:
            raise RuntimeError(f"TTS engine '{failed_eng}' exhausted/failed ({reason}) and no fallback permitted/available.")
        print(f"\n[Block Aligner] {failed_eng.upper()} exhausted/failed ({reason}).")
        print(f"  => Enforcing Single-Engine Rule: Discarding partial {failed_eng} audio and switching to '{nxt.upper()}'...")
        for pf in cache_dir.glob(pattern):
            try:
                pf.unlink()
            except Exception:
                pass
        return synthesize_all_blocks(
            blocks=blocks,
            cache_dir=cache_dir,
            voice=voice,
            engine=nxt,
            sample_rate=sample_rate,
            target_lang=target_lang,
            allow_fallback=allow_fallback,
            exhausted_engines=visited,
        )

    if eng_norm in ("sarvam", "sarvamai"):
        try:
            from .tts import generate_sarvam_tts
            from .key_pool import get_active_sarvam_keys, mark_sarvam_key_dead, is_sarvam_dead_error
        except ImportError:
            from dubbing_studio.tts import generate_sarvam_tts
            from dubbing_studio.key_pool import get_active_sarvam_keys, mark_sarvam_key_dead, is_sarvam_dead_error

        is_en = str(target_lang or "").strip().lower().startswith("en")
        sarvam_lang = "en-IN" if is_en else "hi-IN"
        if voice and ("_en_" in voice or "_hi_" in voice):
            sarvam_speaker = voice
        else:
            sarvam_speaker = "shubh_en_narration" if is_en else "anand_hi_documentary"

        if not get_active_sarvam_keys():
            return _cascade_to_next("sarvam", "all Sarvam keys exhausted before synthesis", "block_sarvam_*.wav")

        sr = 48000

        def _synth_sarvam_block(i: int, b: Dict[str, Any]):
            idx = b.get("index", i)
            raw_text = b.get("text", "").strip()
            spoken_text, _ = extract_audio_tags_and_clean_text(raw_text)
            spoken_text = spoken_text or raw_text
            text_hash = hashlib.md5(f"v4:{sarvam_lang}:{sarvam_speaker}:{spoken_text}".encode("utf-8")).hexdigest()[:8]
            c_file = cache_dir / f"block_sarvam_{idx:03d}_{text_hash}.wav"
            if c_file.exists() and c_file.stat().st_size > 1000:
                raw_audio, audio_sr = sf.read(str(c_file))
                if raw_audio.ndim > 1:
                    raw_audio = raw_audio.mean(axis=1)
                trimmed = trim_audio_silence(raw_audio, threshold=0.010, pad_samples=int(0.01 * audio_sr))
                dur = len(trimmed) / audio_sr
                return i - 1, {"block": b, "audio": trimmed, "sr": audio_sr, "duration": dur, "engine": "sarvam"}

            last_err = None
            for attempt in range(6):
                cur_keys = get_active_sarvam_keys()
                if not cur_keys:
                    raise RuntimeError("All Sarvam API keys exhausted.")
                k = cur_keys[attempt % len(cur_keys)]
                try:
                    generate_sarvam_tts(
                        text=spoken_text,
                        output_path=str(c_file),
                        speaker=sarvam_speaker,
                        language_code=sarvam_lang,
                        model="bulbul:v4-flash",
                        speech_sample_rate=sr,
                        api_key=k,
                    )
                    raw_audio, audio_sr = sf.read(str(c_file))
                    if raw_audio.ndim > 1:
                        raw_audio = raw_audio.mean(axis=1)
                    trimmed = trim_audio_silence(raw_audio, threshold=0.010, pad_samples=int(0.01 * audio_sr))
                    dur = len(trimmed) / audio_sr
                    return i - 1, {"block": b, "audio": trimmed, "sr": audio_sr, "duration": dur, "engine": "sarvam"}
                except Exception as e:
                    last_err = e
                    err_s = str(getattr(e, "body", None) or e)
                    if is_sarvam_dead_error(err_s):
                        mark_sarvam_key_dead(k, reason=err_s[:120])
                        continue
                    time.sleep(1.0 + attempt * 0.5)
            raise RuntimeError(f"Failed to synthesize Sarvam block #{idx:02d}: {last_err}")

        try:
            init_keys = get_active_sarvam_keys()
            max_workers = min(6, max(1, len(init_keys) * 2 if init_keys else 2))
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [ex.submit(_synth_sarvam_block, i, b) for i, b in enumerate(blocks, 1)]
                for fut in as_completed(futures):
                    pos, item = fut.result()
                    results[pos] = item
                    b = item["block"]
                    print(f"  ✓ Block #{b.get('index', pos+1):02d} ready: {item['duration']:.2f}s Sarvam V4 speech (Orig scene: {b['end']-b['start']:.2f}s)")
        except Exception as e:
            return _cascade_to_next("sarvam", str(e)[:120], "block_sarvam_*.wav")

    elif eng_norm in ("google", "gemini"):
        active_gemini = get_active_gemini_keys()
        if not active_gemini:
            return _cascade_to_next("google", "all Gemini keys exhausted before synthesis", "block_google_*.wav")

        active_speaker = voice if (voice and voice.lower() not in ("shubh", "arvind", "amartya", "roger", "brian", "adam")) else "Ludo"
        tts = GoogleGeminiTTS(default_speaker=active_speaker, model="gemini-3.8-flash-tts", style="narration")

        def _synth_google_block(i: int, b: Dict[str, Any]):
            idx = b.get("index", i)
            text = b.get("text", "").strip()
            text_hash = hashlib.md5(f"v2_notag:{text}".encode("utf-8")).hexdigest()[:8]
            c_file = cache_dir / f"block_google_{active_speaker.lower()}_{idx:03d}_{text_hash}.wav"
            if c_file.exists() and c_file.stat().st_size > 1000:
                raw_audio, sr = sf.read(str(c_file))
                trimmed = trim_audio_silence(raw_audio, threshold=0.010, pad_samples=int(0.01 * sr))
                dur = len(trimmed) / sr
                return i - 1, {"block": b, "audio": trimmed, "sr": sr, "duration": dur, "engine": "google"}

            for attempt in range(8):
                if not get_active_gemini_keys():
                    raise RuntimeError("All Gemini API keys exhausted.")
                try:
                    raw_audio, sr = tts.synthesize_single_block(text, voice=active_speaker, cache_path=c_file)
                    trimmed = trim_audio_silence(raw_audio, threshold=0.010, pad_samples=int(0.01 * sr))
                    dur = len(trimmed) / sr
                    return i - 1, {"block": b, "audio": trimmed, "sr": sr, "duration": dur, "engine": "google"}
                except Exception as e:
                    if "exhausted" in str(e).lower() or not get_active_gemini_keys():
                        raise RuntimeError("All Gemini API keys exhausted.")
                    time.sleep(2.0)

            raise RuntimeError(f"Failed to synthesize Google block #{idx:02d} after multiple retries.")

        max_workers = 2
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [ex.submit(_synth_google_block, i, b) for i, b in enumerate(blocks, 1)]
                for fut in as_completed(futures):
                    pos, item = fut.result()
                    results[pos] = item
        except Exception as e:
            return _cascade_to_next("google", str(e)[:120], "block_google_*.wav")

    elif eng_norm in ("elevenlabs", "eleven_labs", "11labs"):
        active_keys = get_active_elevenlabs_keys()
        if not active_keys:
            return _cascade_to_next("elevenlabs", "no active ElevenLabs keys remaining", "block_elevenlabs_*.mp3")

        active_speaker = voice if (voice and voice.lower() not in ("shubh", "arvind", "amartya", "puck", "ludo", "enzo")) else "roger"
        el_lang = "en" if str(target_lang or "").strip().lower().startswith("en") else "hi"
        tts = ElevenLabsTTS(default_voice=active_speaker, language_code=el_lang, model="eleven_v4_turbo")
        max_workers = min(20, max(2, len(active_keys)))

        def _synth_elevenlabs_block(i: int, b: Dict[str, Any]):
            if i <= max_workers and i > 1:
                time.sleep(0.05 * (i - 1))  # 50ms staggered worker launch to prevent simultaneous IP burst flags
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

            for attempt in range(8):
                try:
                    raw_audio, sr = tts.synthesize_single_block(text, voice=active_speaker, cache_path=c_file)
                    trimmed = trim_audio_silence(raw_audio, threshold=0.010, pad_samples=int(0.01 * sr))
                    dur = len(trimmed) / sr
                    return i - 1, {"block": b, "audio": trimmed, "sr": sr, "duration": dur, "engine": "elevenlabs"}
                except Exception as e:
                    if "exhausted" in str(e).lower() or not get_active_elevenlabs_keys():
                        raise RuntimeError("All ElevenLabs API keys in the local runtime pool have been exhausted.")
                    time.sleep(1.0)
            raise RuntimeError(f"ElevenLabs failed to synthesize block #{idx:02d}")

        try:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [ex.submit(_synth_elevenlabs_block, i, b) for i, b in enumerate(blocks, 1)]
                for fut in as_completed(futures):
                    pos, item = fut.result()
                    results[pos] = item
                    b = item["block"]
                    print(f"  ✓ Block #{b.get('index', pos+1):02d} ready: {item['duration']:.2f}s ElevenLabs v4 Turbo speech (Orig scene: {b['end']-b['start']:.2f}s)")
        except Exception as e:
            return _cascade_to_next("elevenlabs", str(e)[:120], "block_elevenlabs_*.mp3")

    elif eng_norm in ("chirp", "google_chirp", "gcloud_chirp"):
        import requests
        import base64
        chirp_key = os.getenv("GOOGLE_TTS_API_KEY") or os.getenv("GEMINI_API_KEY")
        is_en = str(target_lang or "").strip().lower().startswith("en")
        lang_code_chirp = "en-US" if is_en else "hi-IN"
        voice_str = voice or "Orus"
        voice_lower = voice_str.lower()
        if "chirp" in voice_lower:
            chirp_voice = voice_str
        elif voice_lower in ("orus", "fenrir", "puck", "aoede", "charon", "kore", "leto"):
            chirp_voice = f"{lang_code_chirp}-Chirp3-HD-{voice_str.capitalize()}"
        else:
            chirp_voice = f"{lang_code_chirp}-Chirp3-HD-Orus"

        def _synth_chirp_block(i: int, b: Dict[str, Any]):
            idx = b.get("index", i)
            raw_text = b.get("text", "").strip()
            spoken_text, _ = extract_audio_tags_and_clean_text(raw_text)
            spoken_text = spoken_text or raw_text
            text_hash = hashlib.md5(f"v2_notag:{lang_code_chirp}:{spoken_text}".encode("utf-8")).hexdigest()[:8]
            c_file = cache_dir / f"block_chirp_{chirp_voice.split('-')[-1].lower()}_{idx:03d}_{text_hash}.wav"
            if c_file.exists() and c_file.stat().st_size > 1000:
                raw_audio, sr = sf.read(str(c_file))
                trimmed = trim_audio_silence(raw_audio, threshold=0.010, pad_samples=int(0.01 * sr))
                dur = len(trimmed) / sr
                return i - 1, {"block": b, "audio": trimmed, "sr": sr, "duration": dur, "engine": "chirp"}

            url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={chirp_key}"
            payload = {
                "input": {"text": spoken_text},
                "voice": {"languageCode": lang_code_chirp, "name": chirp_voice},
                "audioConfig": {"audioEncoding": "MP3", "speakingRate": 1.05}
            }
            for attempt in range(4):
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
                        return i - 1, {"block": b, "audio": trimmed, "sr": sr, "duration": dur, "engine": "chirp"}
                    if resp.status_code == 429:
                        time.sleep(min(6.0, 0.75 * (2 ** attempt)))
                        continue
                    if resp.status_code in (401, 403):
                        raise RuntimeError(f"Chirp HTTP {resp.status_code}: {resp.text[:100]}")
                    time.sleep(1.0)
                except Exception as ex_req:
                    if "Chirp HTTP" in str(ex_req):
                        raise
                    time.sleep(min(4.0, 0.75 * (attempt + 1)))
            raise RuntimeError(f"Chirp synthesis failed for block #{idx:02d}")

        try:
            with ThreadPoolExecutor(max_workers=8) as ex:
                futures = [ex.submit(_synth_chirp_block, i, b) for i, b in enumerate(blocks, 1)]
                for fut in as_completed(futures):
                    pos, item = fut.result()
                    results[pos] = item
                    b = item["block"]
                    print(f"  ✓ Block #{b.get('index', pos+1):02d} ready: {item['duration']:.2f}s Chirp speech (Orig scene: {b['end']-b['start']:.2f}s)")
        except Exception as e:
            return _cascade_to_next("chirp", str(e)[:120], "block_chirp_*.wav")

    elif eng_norm in ("kokoro", "local", "kokoro_onnx"):
        kokoro_wrapper = _ensure_kokoro_tts()
        kokoro_inst = kokoro_wrapper._get_kokoro()
        is_en = str(target_lang or "").strip().lower().startswith("en")
        k_lang = "en-us" if is_en else "hi"
        k_voice = "am_michael" if is_en else "hm_omega"
        k_sr = 24000

        for i, b in enumerate(blocks, 1):
            idx = b.get("index", i)
            raw_text = b.get("text", "").strip()
            spoken_text, _ = extract_audio_tags_and_clean_text(raw_text)
            spoken_text = spoken_text or raw_text or "."
            text_hash = hashlib.md5(f"kokoro:{k_lang}:{spoken_text}".encode("utf-8")).hexdigest()[:8]
            c_file = cache_dir / f"block_kokoro_{idx:03d}_{text_hash}.wav"
            if c_file.exists() and c_file.stat().st_size > 1000:
                raw_audio, audio_sr = sf.read(str(c_file))
            else:
                raw_audio, audio_sr = kokoro_inst.create(spoken_text, voice=k_voice, speed=1.0, lang=k_lang)
                raw_audio = np.asarray(raw_audio, dtype=np.float32)
                sf.write(str(c_file), raw_audio, int(audio_sr or k_sr))
            if raw_audio.ndim > 1:
                raw_audio = raw_audio.mean(axis=1)
            trimmed = trim_audio_silence(raw_audio, threshold=0.010, pad_samples=int(0.01 * int(audio_sr or k_sr)))
            dur = len(trimmed) / int(audio_sr or k_sr)
            results[i - 1] = {"block": b, "audio": trimmed, "sr": int(audio_sr or k_sr), "duration": dur, "engine": "kokoro"}
            print(f"  ✓ Block #{idx:02d} ready: {dur:.2f}s Local Kokoro speech (Orig scene: {b['end']-b['start']:.2f}s)")

    return [r for r in results if r is not None]


def build_atempo_filter(speed_factor: float) -> str:
    """Chain FFmpeg atempo filters (each clamped between 0.5 and 2.0)."""
    factors = []
    rem = float(speed_factor)
    while rem > 2.0:
        factors.append(2.0)
        rem /= 2.0
    while rem < 0.5:
        factors.append(0.5)
        rem /= 0.5
    factors.append(round(rem, 5))
    return ",".join(f"atempo={f}" for f in factors)


def _plan_movie_timeline(
    block_items: List[Dict[str, Any]],
    vid_dur: float,
    work_dir: Path,
    tts_speed: Optional[float] = None,
    min_gap: float = 0.06,
) -> Tuple[List[Dict[str, Any]], float, float]:
    """
    Build a scene-anchored movie timeline that preserves original gaps and total video duration.
    Avoids compacting the video: places each block at/near its original SRT timestamp (`orig_start`),
    applies uniform speech speedup only when speech overflows `vid_dur`, and pads audio to `max(vid_dur, last_end)`.
    Returns `(aligned_plan, target_timeline_dur, speech_tempo)`.
    """
    def _simulate_end(scale: float) -> float:
        curr = 0.0
        for idx, item in enumerate(block_items, 1):
            orig_start = max(0.0, float(item["block"]["start"]))
            dur_s = max(0.1, float(item["duration"]) / scale)
            start_new = max(0.02, orig_start) if idx == 1 else max(curr + min_gap, orig_start)
            curr = start_new + dur_s
        return curr

    if tts_speed is not None and float(tts_speed) > 0:
        speech_tempo = max(0.75, min(1.75, float(tts_speed)))
        print(f"\n[Block Aligner] Movie Mode Forced Voice Pacing: {speech_tempo:.4f}x (Original Duration Preserved)")
    else:
        if _simulate_end(1.0) <= vid_dur:
            speech_tempo = 1.0
        else:
            lo, hi = 1.0, 1.25
            for _ in range(16):
                mid = 0.5 * (lo + hi)
                if _simulate_end(mid) <= max(0.1, vid_dur - 0.02):
                    hi = mid
                else:
                    lo = mid
            speech_tempo = round(hi, 4)
        print(f"\n[Block Aligner] Movie Mode Anchored Pacing: Voice scale {speech_tempo:.4f}x | Video duration locked near original ({vid_dur:.2f}s)")

    if abs(speech_tempo - 1.0) > 0.005:
        scale_dir = work_dir / "temp_audio_scaled"
        scale_dir.mkdir(parents=True, exist_ok=True)
        atempo_expr = build_atempo_filter(speech_tempo)

        def _scale_clip(idx_item: Tuple[int, Dict[str, Any]]) -> Tuple[int, np.ndarray, int]:
            idx_val, item_val = idx_item
            src_w = scale_dir / f"src_{idx_val:03d}.wav"
            dst_w = scale_dir / f"dst_{idx_val:03d}_{speech_tempo:.4f}.wav"
            sf.write(str(src_w), item_val["audio"], int(item_val["sr"]))
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(src_w), "-filter:a", atempo_expr, str(dst_w)],
                capture_output=True, check=True,
            )
            scaled_arr, scaled_sr = sf.read(str(dst_w), dtype="float32")
            if scaled_arr.ndim > 1:
                scaled_arr = scaled_arr.mean(axis=1)
            return idx_val, scaled_arr, int(scaled_sr)

        with ThreadPoolExecutor(max_workers=4) as ex:
            for idx_val, scaled_arr, scaled_sr in ex.map(_scale_clip, enumerate(block_items)):
                block_items[idx_val]["audio"] = scaled_arr
                block_items[idx_val]["sr"] = scaled_sr
                block_items[idx_val]["duration"] = len(scaled_arr) / scaled_sr

    aligned_plan: List[Dict[str, Any]] = []
    current_timeline_time = 0.0
    print(f"\n[Block Aligner] Sequencing movie blocks at original scene timestamps (min breath gap: {min_gap*1000:.0f}ms)...")
    for idx, item in enumerate(block_items, 1):
        b = item["block"]
        orig_start = max(0.0, float(b["start"]))
        orig_end = max(orig_start, float(b["end"]))
        orig_dur = max(0.1, orig_end - orig_start)
        speech_dur = max(0.1, float(item["duration"]))

        start_new = max(0.02, orig_start) if idx == 1 else max(current_timeline_time + min_gap, orig_start)
        gap_before = start_new - current_timeline_time
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
            "sr": item["sr"],
        })
        print(
            f"  Block #{idx:02d}: {speech_dur:.2f}s speech placed at [{start_new:.2f}s -> {end_new:.2f}s] "
            f"(Orig: {orig_start:.2f}s, Gap: {gap_before:.2f}s)"
        )

    target_timeline_dur = max(vid_dur, current_timeline_time)
    print(
        f"\n[Block Aligner] Movie Speech Span: {current_timeline_time:.2f}s | "
        f"Original Video: {vid_dur:.2f}s | Output Duration: {target_timeline_dur:.2f}s (No Compaction)"
    )
    return aligned_plan, target_timeline_dur, speech_tempo


def align_video_and_audio_blocks(
    clean_video_path: Path,
    srt_path: Path,
    output_video_path: Path,
    sfx_path: Optional[Path] = None,
    bgm_path: Optional[Path] = None,
    voice: str = "shubh",
    engine: str = "sarvam",
    work_dir: Optional[Path] = None,
    max_silence_sec: float = 0.20,
    bgm_volume: float = 1.05,
    mirror: bool = False,
    smart_crop: bool = False,
    burn_subtitles: bool = True,
    tts_speed: Optional[float] = None,
    target_lang: str = "Hindi",
    movie: bool = False,
    watermark: Optional[str] = None,
    ratio: str = "reel",
    disable_bgm: bool = False,
    allow_fallback: bool = True,
    crop_spec_path: Optional[Path] = None,
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
        engine=engine,
        target_lang=target_lang,
        allow_fallback=allow_fallback,
    )

    actual_engine = block_items[0].get("engine", engine) if block_items else engine
    if actual_engine != engine:
        print(f"\n[Block Aligner] Engine reconciled to: {actual_engine.upper()}")
        old_sfx = f"_{engine.lower()}"
        new_sfx = f"_{actual_engine.lower()}"
        engine = actual_engine
        if old_sfx in output_video_path.name:
            output_video_path = output_video_path.with_name(output_video_path.name.replace(old_sfx, new_sfx))
            print(f"[Block Aligner] Updated output video target filename: {output_video_path.name}")

    # Trim trailing dead air on the final block for clean ending / loop closure
    if block_items:
        last_item = block_items[-1]
        mask = np.abs(last_item["audio"]) > 0.010
        if np.any(mask):
            last_idx = np.where(mask)[0][-1]
            last_item["audio"] = last_item["audio"][:last_idx + 1]
            last_item["duration"] = len(last_item["audio"]) / last_item["sr"]

    # 2. Plan Timeline
    if movie:
        aligned_plan, raw_total_speech_dur, reported_voice_tempo = _plan_movie_timeline(
            block_items=block_items,
            vid_dur=vid_dur,
            work_dir=work_dir,
            tts_speed=tts_speed,
            min_gap=0.06,
        )
    else:
        # Plan Unscaled Timeline with Proportional Drift Redistribution (Option 3)
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

    # 3. Assemble Master Voice Audio Buffer
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
    target_samples = max(1, int(round(raw_total_speech_dur * sr_master)))
    sf.write(str(raw_voice_wav), voice_raw_buffer[:target_samples], sr_master)

    # 4. Tempo & Video Duration Reconciliation
    if movie:
        # Timeline already uses original scene positions & speech_tempo; never warp silence gaps or compact video.
        uniform_audio_tempo = 1.0
        timed_voice_wav = raw_voice_wav
        timed_voice_dur = get_media_duration(timed_voice_wav)
        target_video_dur = max(vid_dur, timed_voice_dur)
        video_speedup = vid_dur / target_video_dur
        if abs(video_speedup - 1.0) > 0.01:
            print(f"[Block Aligner] Movie Mode gentle video extend ({vid_dur:.2f}s -> {target_video_dur:.2f}s, {video_speedup:.4f}x) to avoid speech cutoff.")
        else:
            video_speedup = 1.0
            print(f"[Block Aligner] Movie Mode Duration Locked: {target_video_dur:.2f}s (Original Video: {vid_dur:.2f}s, Speedup: 1.0000x)")
    else:
        ideal_audio_tempo = raw_total_speech_dur / vid_dur
        if tts_speed is not None and float(tts_speed) > 0:
            uniform_audio_tempo = max(0.75, min(1.75, float(tts_speed)))
            print(f"\n[Block Aligner] UNIFORM Forced Voice Pacing: Entire narration scaled at {uniform_audio_tempo:.4f}x")
        else:
            # Allow uniform tempo scaling up to 1.25x for energetic viral pacing without voice distortion.
            # If speech is shorter than video, allow gentle expansion down to 0.95x.
            uniform_audio_tempo = max(0.95, min(1.25, ideal_audio_tempo))
            print(f"\n[Block Aligner] UNIFORM Voice Pacing: Entire narration scaled at {uniform_audio_tempo:.4f}x (Allowed 0.95x-1.25x)")
        reported_voice_tempo = uniform_audio_tempo
        timed_voice_wav = work_dir / "timed_uniform_voice.wav"

        cmd_tempo = [
            "ffmpeg", "-y",
            "-i", str(raw_voice_wav),
            "-filter:a", build_atempo_filter(uniform_audio_tempo),
            str(timed_voice_wav)
        ]
        subprocess.run(cmd_tempo, capture_output=True, check=True)
        timed_voice_dur = get_media_duration(timed_voice_wav)
        print(f"[Block Aligner] Final Timed Voiceover Duration: {timed_voice_dur:.2f}s (Original Video: {vid_dur:.2f}s)")

        # CRITICAL LOOP RULE: Voiceover audio must NEVER be cut off at the tail!
        # Video duration is synchronized to match the timed voiceover duration so the audio is 100% complete.
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
                "-filter:a", build_atempo_filter(video_speedup),
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

    # Resolve Royalty-Free Background Music from assets/background_audio/ (unless disabled)
    resolved_bgm = None
    if disable_bgm:
        print("[Block Aligner] Background Music DISABLED (SFX + Voiceover only).")
    elif bgm_path and Path(bgm_path).exists() and Path(bgm_path).is_file():
        resolved_bgm = Path(bgm_path)
    else:
        movie_dirs = [
            root_dir / "assets/background_audio/movie explanation",
            Path("assets/background_audio/movie explanation"),
            Path(__file__).resolve().parent.parent / "assets/background_audio/movie explanation",
        ] if movie else []
        bgm_candidates_dirs = movie_dirs + [
            root_dir / "Background Audios",
            root_dir / "assets/background_audio",
            Path("Background Audios"),
            Path("assets/background_audio"),
            Path(__file__).resolve().parent.parent / "Background Audios",
            Path(__file__).resolve().parent.parent / "assets/background_audio",
        ]
        for d in bgm_candidates_dirs:
            if d and d.exists() and d.is_dir():
                tracks = sorted([f for f in d.glob("*.mp3")] + [f for f in d.glob("*.wav")])
                if tracks:
                    import random
                    resolved_bgm = random.choice(tracks)
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
        "loudnorm=I=-14:TP=-1.5:LRA=7,"
        "aresample=44100"
    )

    # 3-Stem Dynamic Audio Mastering: mastered voice + natural Foley SFX (attenuated 0.58 to kill leak) + increased BGM
    mixed_audio = work_dir / "aligned_mixed_audio.wav"
    bgm_vol = resolve_dynamic_bgm_volume(resolved_bgm, bgm_volume=bgm_volume) if resolved_bgm else 0.18
    bgm_lufs_scale = max(0.45, min(2.5, float(bgm_volume) * 1.25))
    sfx_clean_af = "aresample=44100,highpass=f=40:p=2,volume=0.58"

    # Pre-resolve output video dimensions + optional single-pass crop spec BEFORE audio mixing
    # so word-synced Whisper subtitle generation can overlap with FFmpeg audio mastering (1E + 1F).
    ratio_norm = normalize_aspect_ratio(ratio)
    crop_spec: Optional[Dict[str, Any]] = None
    if crop_spec_path and Path(crop_spec_path).exists():
        try:
            crop_spec = json.loads(Path(crop_spec_path).read_text(encoding="utf-8"))
        except Exception:
            crop_spec = None

    if crop_spec and crop_spec.get("target_w") and crop_spec.get("target_h"):
        v_w = int(crop_spec["target_w"])
        v_h = int(crop_spec["target_h"])
    else:
        probe_dim = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(clean_video_path)],
            capture_output=True, text=True
        )
        v_w, v_h = 1080, 1920
        try:
            parts_d = probe_dim.stdout.strip().splitlines()[0].split("x")
            v_w, v_h = int(parts_d[0]), int(parts_d[1])
        except Exception:
            pass
        if ratio_norm == "square" and (v_w != 1080 or v_h != 1080):
            v_w, v_h = 1080, 1080

    aligned_ass_path = work_dir / f"{clean_video_path.stem}_aligned.ass"
    ass_executor: Optional[ThreadPoolExecutor] = None
    ass_future = None
    if (movie or ratio_norm == "square") and burn_subtitles:
        if ratio_norm == "square":
            movie_margin_v = max(48, int(round(v_h * 0.10)))
        else:
            movie_margin_v = int(round(v_h * (510.0 / 1920.0))) if (v_w / max(1, v_h)) < 0.90 else max(80, int(round(v_h * 0.14)))
        ass_executor = ThreadPoolExecutor(max_workers=1)
        ass_future = ass_executor.submit(
            _generate_word_synced_movie_ass,
            aligned_voice_wav=aligned_voice_wav,
            aligned_plan=aligned_plan,
            ass_path=aligned_ass_path,
            uniform_audio_tempo=uniform_audio_tempo,
            target_lang=target_lang,
            target_w=v_w,
            target_h=v_h,
            margin_v=movie_margin_v,
            ratio=ratio_norm,
        )

    bgm_target_i = -23 if movie else -21
    if aligned_sfx_wav and aligned_sfx_wav.exists() and resolved_bgm and resolved_bgm.exists():
        print(f"[Block Aligner] Dynamic 3-Stem Mastering: Broadcast Mastered Voiceover (-14 LUFS) + Natural Foley SFX (Fix 1+2: no afftdn, preserved dynamics) + BGM ({resolved_bgm.name}, ducked {bgm_target_i} LUFS @ {bgm_volume:.2f}x)...")
        filter_mix = (
            f"[0:a]{voice_master_af},asplit=3[voice_main][voice_key_sfx][voice_key_bgm];"
            f"[1:a]{sfx_clean_af}[sfx_clean];"
            "[sfx_clean][voice_key_sfx]sidechaincompress=threshold=0.06:ratio=2.2:attack=15:release=180[sfx_ducked];"
            f"[2:a]atrim=0:{target_video_dur + 0.5:.3f},asetpts=PTS-STARTPTS,loudnorm=I={bgm_target_i}:TP=-2:LRA=8,aresample=44100,volume={bgm_lufs_scale:.3f}[music_raw];"
            "[music_raw][voice_key_bgm]sidechaincompress=threshold=0.05:ratio=2.5:attack=20:release=250[music];"
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
        print(f"[Block Aligner] Dynamic 2-Stem Mastering: Broadcast Mastered Voiceover (-14 LUFS) + Natural Foley SFX (Fix 1+2: no afftdn, preserved dynamics)...")
        filter_mix = (
            f"[0:a]{voice_master_af},asplit=2[voice_main][voice_key];"
            f"[1:a]{sfx_clean_af}[sfx_clean];"
            "[sfx_clean][voice_key]sidechaincompress=threshold=0.06:ratio=2.2:attack=15:release=180[sfx_ducked];"
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
        print(f"[Block Aligner] Dynamic 2-Stem Mastering: Broadcast Mastered Voiceover (-14 LUFS) + BGM ({resolved_bgm.name}, ducked {bgm_target_i} LUFS @ {bgm_volume:.2f}x)...")
        filter_mix = (
            f"[0:a]{voice_master_af},asplit=2[voice_main][voice_key_bgm];"
            f"[1:a]atrim=0:{target_video_dur + 0.5:.3f},asetpts=PTS-STARTPTS,loudnorm=I={bgm_target_i}:TP=-2:LRA=8,aresample=44100,volume={bgm_lufs_scale:.3f}[music_raw];"
            "[music_raw][voice_key_bgm]sidechaincompress=threshold=0.045:ratio=2.8:attack=25:release=350[music];"
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

    if ass_future is not None:
        try:
            ass_future.result()
        finally:
            if ass_executor:
                ass_executor.shutdown(wait=False)
    else:
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

    # 6. Final Mux: Single-Pass Crop + Filters + Subtitles + Watermark using GPU NVENC (libx264 fallback)
    vf_post: List[str] = []
    if mirror:
        print("[Block Aligner] Anti-Copyright Active: Applying horizontal mirroring (hflip) + cinematic color grade hash alteration...")
        vf_post.append("hflip,eq=contrast=1.07:brightness=0.01:saturation=1.12")
    if abs(video_speedup - 1.0) > 0.01:
        vf_post.append(f"setpts=PTS/{video_speedup:.5f}")
    if ratio_norm == "square" and not (crop_spec and crop_spec.get("crop_mode") == "square"):
        probe_cur = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(clean_video_path)],
            capture_output=True, text=True
        )
        cur_w, cur_h = v_w, v_h
        try:
            cur_d = probe_cur.stdout.strip().splitlines()[0].split("x")
            cur_w, cur_h = int(cur_d[0]), int(cur_d[1])
        except Exception:
            pass
        if cur_w != 1080 or cur_h != 1080:
            print(f"[Block Aligner] Square Aspect Ratio: Formatting {cur_w}x{cur_h} -> full-bleed 1080x1080 (1:1)")
            vf_post.append("scale=1080:1080:force_original_aspect_ratio=increase:flags=bicubic,crop=1080:1080")
            v_w, v_h = 1080, 1080

    print(f"\n[Block Aligner] Muxing final video to: {output_video_path} (Target duration: {target_video_dur:.2f}s)...")
    escaped_ass = str(aligned_ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
    fonts_dir_path = root_dir / "assets" / "fonts"
    fonts_arg = f":fontsdir='{str(fonts_dir_path.resolve()).replace(chr(92), '/').replace(':', chr(92) + ':')}'" if fonts_dir_path.exists() else ""
    if burn_subtitles and not smart_crop:
        vf_post.append(f"subtitles='{escaped_ass}'{fonts_arg}")
    elif smart_crop:
        print("[Block Aligner] Smart Crop Mode: Bottom subtitle burn disabled (clean cropped portrait layout).")

    # Integrate optional deferred single-pass crop_spec (1F) before post filters
    pre_fc = ""
    pre_out_pad = "[0:v]"
    linear_crop_vf = ""
    if crop_spec:
        cmode = crop_spec.get("crop_mode")
        if cmode == "reels_blur":
            print(
                f"[Block Aligner Single-Pass] Reels Crop+Blur: {crop_spec.get('crop_w')}x{crop_spec.get('crop_h')} -> "
                f"1080x1920 ({float(crop_spec.get('zoom', 1.15)):.2f}x foreground + blurred bars)"
            )
            c_pref = crop_spec.get("crop_prefix", "")
            pre_fc = (
                f"[0:v]{c_pref}split=2[mc_fg][mc_bg];"
                f"[mc_bg]scale=1080:1920:force_original_aspect_ratio=increase,"
                f"crop=1080:1920,boxblur=30:3[mc_bg_blur];"
                f"[mc_fg]scale={crop_spec['scale_w']}:{crop_spec['fg_scaled_h']}:flags=bicubic,"
                f"crop=1080:{crop_spec['fg_crop_h']}:{crop_spec['fg_crop_x']}:{crop_spec['fg_crop_y']}[mc_fg_zoom];"
                f"[mc_bg_blur][mc_fg_zoom]overlay=(W-w)/2:(H-h)/2[mc_out]"
            )
            pre_out_pad = "[mc_out]"
        elif crop_spec.get("vf"):
            print(f"[Block Aligner Single-Pass] {cmode.capitalize()} filter fused into final encode ({v_w}x{v_h}).")
            linear_crop_vf = str(crop_spec["vf"])

    vf_parts = ([linear_crop_vf] if linear_crop_vf else []) + vf_post

    cmd_mux_base = [
        "ffmpeg", "-y", "-threads", "0",
        "-i", str(clean_video_path),
        "-i", str(final_audio_path),
    ]
    clean_wm = " ".join(str(watermark or "").strip().split())
    if clean_wm:
        from .watermark import create_watermark_strip_png, build_watermark_filter_complex
        strip_png, mask_png, wm_band_h, wm_band_top = create_watermark_strip_png(
            watermark_text=clean_wm,
            video_w=v_w,
            video_h=v_h,
            output_png=work_dir / "channel_watermark_strip.png",
        )
        fc, vpad = build_watermark_filter_complex(
            base_vf=",".join(vf_parts),
            video_w=v_w,
            band_h=wm_band_h,
            y_band_top=wm_band_top,
            wm_input_idx=2,
            mask_input_idx=3,
            pre_fc=pre_fc,
            pre_out_pad=pre_out_pad,
        )
        print(f"[Block Aligner] Channel Watermark (Zero-Band SoftLight Blend): '{clean_wm.upper()}' @ y={wm_band_top}..{wm_band_top + wm_band_h}")
        cmd_mux_base.extend([
            "-loop", "1", "-t", f"{target_video_dur + 1.0:.3f}", "-i", str(strip_png),
            "-loop", "1", "-t", f"{target_video_dur + 1.0:.3f}", "-i", str(mask_png),
        ])
        cmd_mux_base.extend(["-filter_complex", fc, "-map", vpad, "-map", "1:a:0"])
    elif pre_fc:
        if vf_parts:
            full_fc = f"{pre_fc};{pre_out_pad}{','.join(vf_parts)}[vout]"
            vpad = "[vout]"
        else:
            full_fc = pre_fc
            vpad = pre_out_pad
        cmd_mux_base.extend(["-filter_complex", full_fc, "-map", vpad, "-map", "1:a:0"])
    else:
        if vf_parts:
            cmd_mux_base.extend(["-vf", ",".join(vf_parts)])
        cmd_mux_base.extend(["-map", "0:v:0", "-map", "1:a:0"])

    tail_flags = [
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{target_video_dur:.3f}",
        "-shortest",
        str(output_video_path),
    ]
    mux_log = work_dir / "ffmpeg_mux.log"
    res = None
    if _ffmpeg_has_nvenc():
        nv_cmd = cmd_mux_base + [
            "-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "19", "-b:v", "0", "-pix_fmt", "yuv420p"
        ] + tail_flags
        with open(mux_log, "w", encoding="utf-8", errors="replace") as f_log:
            res = subprocess.run(nv_cmd, stdout=f_log, stderr=subprocess.STDOUT)
        if res.returncode != 0:
            print("[Block Aligner] NVENC fallback -> retrying cleanly with CPU libx264...")

    if res is None or res.returncode != 0:
        cpu_cmd = cmd_mux_base + [
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p"
        ] + tail_flags
        with open(mux_log, "w", encoding="utf-8", errors="replace") as f_log:
            res = subprocess.run(cpu_cmd, stdout=f_log, stderr=subprocess.STDOUT)

    if res.returncode != 0:
        err_tail = mux_log.read_text(encoding="utf-8", errors="replace")[-1000:]
        print(f"[Block Aligner] Mux Error:\n{err_tail}")
        raise subprocess.CalledProcessError(res.returncode, cpu_cmd, output=err_tail)

    print(f"\n🎉 [SUCCESS] Uniform Aligned Video Ready!")
    print(f"   📹 File: {output_video_path}")
    print(f"   ⏱️ Duration: {target_video_dur:.2f}s")
    print(f"   🎙️ Voice Engine: {engine.capitalize()} ({voice}) | Scaling: {reported_voice_tempo:.4f}x (Uniform across all blocks)")

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
