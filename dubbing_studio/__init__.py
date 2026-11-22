#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio
==============
Modular Video Localization & Automated Dubbing Studio.
"""

from .env_loader import configure_runtime_environment
from .key_pool import (
    get_active_gemini_keys,
    mark_gemini_key_dead,
    get_active_sarvam_keys,
    mark_sarvam_key_dead,
    get_active_elevenlabs_keys,
    mark_elevenlabs_key_dead,
    get_pool_status,
)
from .downloader import DownloaderAPI
from .transcriber import Transcriber
try:
    from .translator import (
        SRTDubTranslator,
        inject_constraints_into_srt,
        clean_and_verify_srt,
        translate_and_rewrite_srt,
        SYSTEM_PROMPT,
    )
except ImportError:
    SRTDubTranslator = None
    inject_constraints_into_srt = None
    clean_and_verify_srt = None
    translate_and_rewrite_srt = None
    SYSTEM_PROMPT = None

try:
    from .tts_engine import KokoroTTS
except ImportError:
    KokoroTTS = None

try:
    from .tts import SarvamTTS, generate_sarvam_tts
except ImportError:
    SarvamTTS = None
    generate_sarvam_tts = None

try:
    from .tts_google import GoogleGeminiTTS
except ImportError:
    GoogleGeminiTTS = None

try:
    from .tts_elevenlabs import ElevenLabsTTS
except ImportError:
    ElevenLabsTTS = None

try:
    from .tts_omnivoice import OmniVoiceTTS
except ImportError:
    OmniVoiceTTS = None

try:
    from .separator import AudioStemSeparator
except ImportError:
    AudioStemSeparator = None
from .anti_accent import (
    balance_consecutive_english,
    count_syllables,
    english_to_devanagari,
)


def __getattr__(name: str):
    if name == "DubbingPipeline":
        from .pipeline import DubbingPipeline
        return DubbingPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "configure_runtime_environment",
    "DownloaderAPI",
    "Transcriber",
    "SRTDubTranslator",
    "KokoroTTS",
    "SarvamTTS",
    "GoogleGeminiTTS",
    "ElevenLabsTTS",
    "OmniVoiceTTS",
    "AudioStemSeparator",
    "generate_sarvam_tts",
    "DubbingPipeline",
    "inject_constraints_into_srt",
    "clean_and_verify_srt",
    "translate_and_rewrite_srt",
    "SYSTEM_PROMPT",
]

