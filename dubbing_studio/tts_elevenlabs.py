#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/tts_elevenlabs.py
================================
ElevenLabs TTS Engine with Multi-Key Pooler, Auto-Rotation & Runtime Eviction.

Features:
- High-fidelity voiceover synthesis using ElevenLabs v4 (eleven_v4).
- Multi-Key Round-Robin Rotation across 10-15 keys for parallel throughput.
- Runtime dead/quota key eviction (401, 402, 429) without modifying .env files.
- Thread-safe parallel block synthesis with disk caching and silence trimming.
- Fallback model waterfall (eleven_v4 -> eleven_multilingual_v2 -> eleven_turbo_v2_5).
"""

import io
import os
import re
import time
import hashlib
import logging
import threading
import subprocess
from pathlib import Path
from typing import Optional, Union, List, Dict, Tuple, Iterator

import numpy as np
import soundfile as sf

from .key_pool import (
    get_active_elevenlabs_keys,
    mark_elevenlabs_key_dead,
    is_elevenlabs_dead_error,
    mask_key,
)

logger = logging.getLogger("dubbing_studio.tts_elevenlabs")

# Curated ElevenLabs Voice IDs for expressive narration
ELEVENLABS_VOICES: Dict[str, str] = {
    # High-retention narration voices
    "viraj": "FmBhnvP58BK0vz65OOj7",     # Viraj (Hindi Narrator - Default)
    "brian": "nPczCjzI2devNBz1zQrb",     # Deep, compelling narration
    "adam": "pNInz6obpgDQGcFmaJgB",      # Deep, classic narrative
    "roger": "CwhRBWXzGAHq8TQ4Fs17",     # Confident, lively storyteller
    "charlie": "IKne3meq5aSn9XLyUdCD",   # Casual, energetic Aussie
    "george": "JBFqnCBsd6RMkjVDRZzb",    # Warm, captivating storyteller
    "liam": "TX3LPaxmHKxFdv7VOQHJ",      # Articulate, young narrator
    "callum": "N2lVS1w4EtoT3dr4eOWO",    # Intense, dramatic
    "river": "SAz9YHcvj6GT2YYXdXww",     # Confident, neutral
    "sarah": "EXAVITQu4vr4xnSDxMaL",     # Expressive, warm female
    "laura": "FGY2WhTYpPnrIDTdsKH5",     # Enthusiastic female
    "jessica": "cgSgspJ2msm6clMCkdW9",   # Playful, bright female
    "eric": "cjVigY5qzO86Huf0OWal",      # Friendly, conversational
    "chris": "iP95p4xoKVk53GoZ742B",     # Charming, conversational
    "daniel": "onwK4e9ZLuTAKqWW03F9",    # Authoritative news/documentary
    "lily": "pFZP5JQG7iQjIQuC4Bku",      # Velvety, calm narrator
    "bill": "pqHfZKP75CvOlQylNhV4",      # Grounded, trustworthy
}

DEFAULT_ELEVENLABS_VOICE = "roger"
DEFAULT_ELEVENLABS_LANGUAGE = "hi"


def resolve_voice_id(voice: Optional[str]) -> str:
    """Resolve friendly voice name or direct ID to an ElevenLabs voice ID."""
    if not voice:
        return ELEVENLABS_VOICES[DEFAULT_ELEVENLABS_VOICE]
    v_clean = voice.strip().lower()
    if v_clean in ELEVENLABS_VOICES:
        return ELEVENLABS_VOICES[v_clean]
    # If the user passed a direct 20-character voice ID
    if len(voice.strip()) >= 15:
        return voice.strip()
    return ELEVENLABS_VOICES.get(v_clean, ELEVENLABS_VOICES[DEFAULT_ELEVENLABS_VOICE])



def trim_audio_silence(audio: np.ndarray, threshold: float = 0.010, pad_samples: int = 240) -> np.ndarray:
    """Trim leading and trailing silence from audio waveform."""
    if len(audio) == 0:
        return audio
    mask = np.abs(audio) > threshold
    if not np.any(mask):
        return audio
    first = max(0, int(np.argmax(mask) - pad_samples))
    last = min(len(audio), int(len(mask) - np.argmax(mask[::-1]) + pad_samples))
    return audio[first:last]


def adjust_audio_speed(audio: np.ndarray, sample_rate: int, speed: float) -> np.ndarray:
    """Smooth tempo compression using ffmpeg atempo filter."""
    if abs(speed - 1.0) < 0.03:
        return audio

    temp_in = io.BytesIO()
    sf.write(temp_in, audio, sample_rate, format="WAV")
    wav_bytes = temp_in.getvalue()

    safe_speed = max(0.8, min(speed, 1.40))
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


class ElevenLabsTTS:
    """
    ElevenLabs v4 TTS Engine with Key Pooler, Auto-Rotation & Runtime Eviction.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_voice: str = "roger",
        language_code: str = "hi",
        model: str = "eleven_v4_turbo"
    ):
        active_pool = get_active_elevenlabs_keys()
        if api_key:
            self._explicit_single_key = api_key.strip()
            self.api_keys = [self._explicit_single_key]
        else:
            self._explicit_single_key = None
            self.api_keys = active_pool

        if not self.api_keys:
            raise ValueError(
                "No active ELEVENLABS_API_KEY or ELEVENLABS_API_KEYS available in local pool."
            )

        self.key_idx = 0
        self._key_lock = threading.Lock()
        self.default_voice = default_voice
        self.language_code = language_code
        self.model = model
        # Waterfall: eleven_v4_turbo first as default, then eleven_v4, then multilingual v2, then turbo v2.5
        self.fallback_models = [
            "eleven_v4_turbo",
            "eleven_v4",
            "eleven_multilingual_v2",
            "eleven_turbo_v2_5",
        ]
        if self.model not in self.fallback_models:
            self.fallback_models.insert(0, self.model)

    def get_client(self):
        """Thread-safe retrieval of current ElevenLabs client with an active key from the local pool."""
        from elevenlabs.client import ElevenLabs

        with self._key_lock:
            if not self._explicit_single_key:
                # Filter against live active pool (never re-adds exhausted keys)
                active_pool = get_active_elevenlabs_keys()
                active_set = set(active_pool)
                self.api_keys = [k for k in self.api_keys if k in active_set]
                if not self.api_keys:
                    self.api_keys = active_pool
            if not self.api_keys:
                raise RuntimeError("All ElevenLabs API keys in the local runtime pool have been exhausted.")
            idx = self.key_idx % len(self.api_keys)
            key = self.api_keys[idx]
            self.key_idx = (idx + 1) % len(self.api_keys)
        return ElevenLabs(api_key=key), key

    def rotate_key(self, dead_key: Optional[str] = None, reason: str = ""):
        """Thread-safe round-robin key rotation and dead key eviction."""
        with self._key_lock:
            if dead_key:
                mark_elevenlabs_key_dead(dead_key, reason=reason)
                if dead_key in self.api_keys:
                    self.api_keys.remove(dead_key)
            if self.api_keys:
                self.key_idx = (self.key_idx + 1) % len(self.api_keys)
                new_idx = self.key_idx
                masked = mask_key(self.api_keys[new_idx])
                if not dead_key:
                    logger.debug(f"[ElevenLabs Rotation] Switched to Key #{new_idx + 1}/{len(self.api_keys)} ({masked})")

    def synthesize_single_block(
        self,
        text: str,
        voice: Optional[str] = None,
        language_code: Optional[str] = None,
        cache_path: Optional[Path] = None,
        max_retries: int = 10
    ) -> Tuple[np.ndarray, int]:
        """
        Synthesize a single subtitle line with automatic retry, model fallback,
        and round-robin key rotation with instant runtime eviction.
        """
        # 1. Check disk cache
        if cache_path and cache_path.exists() and cache_path.stat().st_size > 500:
            try:
                audio, sr = sf.read(str(cache_path))
                if audio.ndim > 1:
                    audio = audio.mean(axis=1)
                return audio.astype(np.float32), sr
            except Exception:
                pass

        current_lang = (language_code or self.language_code or "hi").strip().lower()
        clean_text = text.strip()
        # ElevenLabs v4 natively interprets bracketed Audio Tags like [laughs], [gasps], [whispers] as expressive performance cues.
        # Ensure trailing dashes/hyphens/dangling punctuation are sanitized to prevent hallucinated noises
        clean_text = re.sub(r"[\s—–\-~…\.]+$", "", clean_text).strip()
        clean_text = re.sub(r"\s*[—–\-~]\s*", ", ", clean_text).strip()
        clean_text = " ".join(clean_text.split())
        # Ensure a clean closing punctuation so the vocoder knows the sentence has finished
        if clean_text and not clean_text.endswith((".", "!", "?", "।")):
            clean_text += "।" if current_lang.startswith("hi") else "."
        if not clean_text:
            return np.zeros(2400, dtype=np.float32), 24000

        voice_id = resolve_voice_id(voice or self.default_voice)
        # Keep consistent model (eleven_v4) across all blocks so voice tone, pronunciation, and style never abruptly shift
        target_model = self.model or "eleven_v4_turbo"

        from elevenlabs import VoiceSettings
        voice_settings = VoiceSettings(
            stability=0.65,
            similarity_boost=0.75,
            style=0.15,
            use_speaker_boost=True
        )

        total_attempts = max(max_retries, len(self.api_keys) + 2)
        for attempt in range(total_attempts):
            if not self.api_keys and not get_active_elevenlabs_keys():
                raise RuntimeError("All ElevenLabs API keys in the runtime pool have been exhausted.")

            current_model = target_model
            client, active_key = self.get_client()

            try:
                # Convert text to speech via ElevenLabs v4 with native Hindi language support
                audio_stream = client.text_to_speech.convert(
                    voice_id=voice_id,
                    text=clean_text,
                    model_id=current_model,
                    voice_settings=voice_settings,
                    language_code=current_lang,
                    output_format="mp3_44100_128"
                )

                # Collect all bytes from generator
                raw_bytes = b"".join(audio_stream)
                if not raw_bytes or len(raw_bytes) < 100:
                    raise ValueError("Received empty or corrupt audio response from ElevenLabs")

                # Parse audio bytes
                audio, sr = sf.read(io.BytesIO(raw_bytes))
                if audio.ndim > 1:
                    audio = audio.mean(axis=1)
                audio = audio.astype(np.float32)

                # Round-robin rotate key for next request to balance load
                self.rotate_key()

                # Save to cache if requested
                if cache_path:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    sf.write(str(cache_path), audio, sr)

                return audio, sr

            except Exception as e:
                err_str = str(e)
                status_code = getattr(e, "status_code", None)
                err_body = getattr(e, "body", None)
                detail_msg = f"HTTP {status_code}: {err_body}" if (status_code or err_body) else err_str
                # If library voice is restricted on free tier, gracefully fall back to official Hindi narrator Brian
                if ("library voice" in err_str.lower() or "library_voice" in err_str.lower() or "paid_plan_required" in err_str.lower()) and voice_id != ELEVENLABS_VOICES["brian"]:
                    print(f"      [ElevenLabs Notice] Voice '{voice or self.default_voice}' is a Community Library voice requiring paid credits. Auto-falling back to official Hindi narrator 'Brian'...")
                    voice_id = ELEVENLABS_VOICES["brian"]
                    continue
                if is_elevenlabs_dead_error(err_str, status_code=status_code, body=err_body):
                    self.rotate_key(dead_key=active_key, reason=str(detail_msg)[:120])
                    if not self._explicit_single_key and not get_active_elevenlabs_keys():
                        raise RuntimeError("All ElevenLabs API keys in the local runtime pool have been exhausted.")
                    if self._explicit_single_key:
                        raise RuntimeError(f"Explicit ElevenLabs key exhausted: {str(detail_msg)[:120]}")
                    time.sleep(0.25)
                else:
                    print(f"      [ElevenLabs Notice on {current_model}] {str(detail_msg)[:100]}. Retrying next key...")
                    self.rotate_key()
                    time.sleep(1.0)

        raise RuntimeError(f"ElevenLabs TTS failed to synthesize: {clean_text[:40]}...")

